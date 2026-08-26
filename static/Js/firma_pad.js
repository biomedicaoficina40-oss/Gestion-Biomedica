/* ════════════════════════════════════════════════════════════════════════
   Pad de firma táctil — sin dependencias.

   Se usa en el formulario de alta y en el visor del reporte, por eso vive
   en un archivo compartido en vez de ir embebido en la plantilla como el
   resto del JS del proyecto.

   Uso:
     <div class="firma-pad" data-firma-pad data-input="idDelInputHidden">
       <canvas></canvas>
     </div>

   El trazo se vuelca al <input type="hidden"> indicado, como data URL PNG,
   cada vez que se levanta el dedo. Vacío = cadena vacía.
   ════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const ALTO_CSS   = 150;   // alto visible del pad, en px
  const COLOR      = '#111827';
  const GROSOR     = 2.2;

  class FirmaPad {
    constructor(contenedor) {
      this.cont   = contenedor;
      this.canvas = contenedor.querySelector('canvas');
      this.input  = document.getElementById(contenedor.dataset.input);
      this.ctx    = this.canvas.getContext('2d');
      this.dibujando = false;
      this.vacio     = true;
      this.ultimo    = null;

      this.anchoActual = 0;
      this._ajustarLienzo();
      this._conectar();

      /* El lienzo se remide cada vez que el contenedor cambia de ancho.
         Hace falta un observador y no solo el resize de la ventana: al
         construirse el pad el CSS externo puede no haber aplicado todavía
         y clientWidth vale 0, lo que dejaría un búfer de 1px dibujando
         sobre un canvas mostrado a 300. También cubre rotar el teléfono y
         los paneles que nacen ocultos. */
      if (window.ResizeObserver) {
        this._observador = new ResizeObserver(() => this._ajustarLienzo(true));
        this._observador.observe(this.cont);
      } else {
        this._onResize = () => this._ajustarLienzo(true);
        window.addEventListener('resize', this._onResize);
      }
    }

    /* El canvas se dibuja a la resolución real del dispositivo y se muestra
       al tamaño CSS: sin esto el trazo sale pixeleado en pantallas densas,
       que es justo donde se va a firmar (celulares). */
    _ajustarLienzo(conservar) {
      const dpr   = window.devicePixelRatio || 1;
      const ancho = this.cont.clientWidth;

      // Contenedor todavía sin ancho (oculto o CSS sin aplicar): no se
      // toca el lienzo. El observador volverá a llamar cuando lo tenga.
      if (ancho < 1) return;
      if (conservar && Math.abs(ancho - this.anchoActual) < 1) return;

      const previo = (conservar && !this.vacio) ? this.canvas.toDataURL('image/png') : null;
      const anchoPrevio = this.anchoActual;
      this.anchoActual  = ancho;

      this.canvas.style.width  = '100%';
      this.canvas.style.height = ALTO_CSS + 'px';
      this.canvas.width  = Math.max(Math.round(ancho * dpr), 1);
      this.canvas.height = Math.round(ALTO_CSS * dpr);

      this.ctx = this.canvas.getContext('2d');
      this.ctx.scale(dpr, dpr);
      this.ctx.lineWidth   = GROSOR;
      this.ctx.lineCap     = 'round';
      this.ctx.lineJoin    = 'round';
      this.ctx.strokeStyle = COLOR;

      if (previo && anchoPrevio > 0) {
        // El trazo se reproyecta al ancho nuevo para no perderlo al rotar.
        const img = new Image();
        img.onload = () => this.ctx.drawImage(img, 0, 0, ancho, ALTO_CSS);
        img.src = previo;
      }
    }

    _punto(ev) {
      const r = this.canvas.getBoundingClientRect();
      return { x: ev.clientX - r.left, y: ev.clientY - r.top };
    }

    _conectar() {
      /* Pointer Events cubren dedo, stylus y ratón con un solo camino.
         El canvas lleva touch-action:none en el CSS; sin eso, en celular el
         gesto de dibujar hace scroll de la página en lugar de trazar. */
      this.canvas.addEventListener('pointerdown', (ev) => {
        ev.preventDefault();
        this.canvas.setPointerCapture(ev.pointerId);
        this.dibujando = true;
        this.ultimo = this._punto(ev);

        // Un toque simple sin arrastre también deja marca (un punto).
        this.ctx.beginPath();
        this.ctx.arc(this.ultimo.x, this.ultimo.y, GROSOR / 2, 0, Math.PI * 2);
        this.ctx.fillStyle = COLOR;
        this.ctx.fill();
        this._marcarUsado();
      });

      this.canvas.addEventListener('pointermove', (ev) => {
        if (!this.dibujando) return;
        ev.preventDefault();
        const p = this._punto(ev);
        this.ctx.beginPath();
        this.ctx.moveTo(this.ultimo.x, this.ultimo.y);
        this.ctx.lineTo(p.x, p.y);
        this.ctx.stroke();
        this.ultimo = p;
      });

      const terminar = (ev) => {
        if (!this.dibujando) return;
        this.dibujando = false;
        this.ultimo = null;
        if (ev.pointerId !== undefined && this.canvas.hasPointerCapture(ev.pointerId)) {
          this.canvas.releasePointerCapture(ev.pointerId);
        }
        this._volcar();
      };
      this.canvas.addEventListener('pointerup', terminar);
      this.canvas.addEventListener('pointercancel', terminar);
      this.canvas.addEventListener('pointerleave', terminar);

      const btn = this.cont.parentElement.querySelector('[data-firma-limpiar]');
      if (btn) btn.addEventListener('click', () => this.limpiar());
    }

    _marcarUsado() {
      this.vacio = false;
      this.cont.classList.add('firmado');
    }

    _volcar() {
      if (this.input) {
        this.input.value = this.vacio ? '' : this.canvas.toDataURL('image/png');
      }
      this.cont.dispatchEvent(new CustomEvent('firma:cambio', {
        bubbles: true,
        detail: { vacio: this.vacio },
      }));
    }

    limpiar() {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
      this.vacio = true;
      this.cont.classList.remove('firmado');
      this._volcar();
    }

    estaVacio() { return this.vacio; }
  }

  const registro = new WeakMap();

  function iniciar(raiz) {
    (raiz || document).querySelectorAll('[data-firma-pad]').forEach((cont) => {
      if (registro.has(cont)) return;
      registro.set(cont, new FirmaPad(cont));
    });
  }

  /* API mínima para las plantillas: saber si un pad está vacío y limpiarlo. */
  window.FirmaPad = {
    iniciar: iniciar,
    de: (cont) => registro.get(cont),
    estaVacio: (cont) => {
      const pad = registro.get(cont);
      return pad ? pad.estaVacio() : true;
    },
    limpiar: (cont) => {
      const pad = registro.get(cont);
      if (pad) pad.limpiar();
    },
    /* Vuelve a medir un pad que acaba de hacerse visible.
       Hace falta porque un pad que nace dentro de un contenedor con
       `display:none` —una pestaña, un acordeón, un modal— no tiene caja, y el
       ResizeObserver no dispara de forma fiable al aparecer: el lienzo se
       queda con el búfer por omisión de 300x150 mostrado a otro tamaño, así
       que el trazo aparece desplazado respecto al dedo.
       Llámalo al mostrar el contenedor. Si el pad ya estaba bien medido no
       hace nada. */
    remedir: (cont) => {
      const pad = registro.get(cont);
      if (pad) pad._ajustarLienzo(true);
    },
    /* Remide todos los pads visibles bajo `raiz`. */
    remedirTodos: (raiz) => {
      (raiz || document).querySelectorAll('[data-firma-pad]').forEach((cont) => {
        const pad = registro.get(cont);
        if (pad) pad._ajustarLienzo(true);
      });
    },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => iniciar());
  } else {
    iniciar();
  }
})();
