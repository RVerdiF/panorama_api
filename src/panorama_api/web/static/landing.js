/* ============================================================
   Panorama Escola — landing: movimento e leitura
   Sem dependências. Tudo respeita prefers-reduced-motion.
   ============================================================ */
(function () {
  "use strict";

  var reduzir = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* só esconde blocos para revelar se o JS está de fato rodando */
  document.documentElement.classList.add("js");

  /* ---------- formatação pt-BR ---------- */
  function formatar(valor, casas) {
    return valor.toLocaleString("pt-BR", {
      minimumFractionDigits: casas,
      maximumFractionDigits: casas
    });
  }

  /* ---------- contadores ---------- */
  function contar(el) {
    var alvo = parseFloat(el.getAttribute("data-contar"));
    var casas = parseInt(el.getAttribute("data-decimais") || "0", 10);
    if (isNaN(alvo)) return;

    if (reduzir) { el.textContent = formatar(alvo, casas); return; }

    var duracao = 1300;
    var inicio = null;

    function passo(agora) {
      if (inicio === null) inicio = agora;
      var t = Math.min((agora - inicio) / duracao, 1);
      // easeOutCubic
      var e = 1 - Math.pow(1 - t, 3);
      el.textContent = formatar(alvo * e, casas);
      if (t < 1) requestAnimationFrame(passo);
      else el.textContent = formatar(alvo, casas);
    }
    requestAnimationFrame(passo);
  }

  /* ---------- revelação por rolagem ---------- */
  var revelar = document.querySelectorAll("[data-reveal]");
  var observarBarras = document.querySelectorAll("[data-observar]");
  var contadores = document.querySelectorAll("[data-contar]");

  if (!("IntersectionObserver" in window) || reduzir) {
    revelar.forEach(function (el) { el.classList.add("is-in"); });
    observarBarras.forEach(function (el) { el.classList.add("is-in"); });
    contadores.forEach(contar);
  } else {
    var ioRevelar = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (entrada) {
        if (entrada.isIntersecting) {
          entrada.target.classList.add("is-in");
          ioRevelar.unobserve(entrada.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });

    revelar.forEach(function (el) { ioRevelar.observe(el); });

    var ioBarras = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (entrada) {
        if (entrada.isIntersecting) {
          entrada.target.classList.add("is-in");
          ioBarras.unobserve(entrada.target);
        }
      });
    }, { threshold: 0.35 });

    observarBarras.forEach(function (el) { ioBarras.observe(el); });

    var ioContar = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (entrada) {
        if (entrada.isIntersecting) {
          contar(entrada.target);
          ioContar.unobserve(entrada.target);
        }
      });
    }, { threshold: 0.6 });

    contadores.forEach(function (el) { ioContar.observe(el); });
  }

  /* ---------- navegação: estado compacto + progresso ---------- */
  var nav = document.getElementById("nav");
  var progresso = document.getElementById("progresso");
  var agendado = false;

  function aoRolar() {
    var topo = window.scrollY || document.documentElement.scrollTop;
    if (nav) nav.setAttribute("data-compacto", topo > 8 ? "true" : "false");

    if (progresso) {
      var altura = document.documentElement.scrollHeight - window.innerHeight;
      var pct = altura > 0 ? Math.min(Math.max(topo / altura, 0), 1) * 100 : 0;
      progresso.style.width = pct.toFixed(2) + "%";
    }

    /* paralaxe discreta da fotografia */
    var foto = document.querySelector(".banda__moldura img");
    if (foto && !reduzir) {
      var caixa = foto.parentElement.getBoundingClientRect();
      var centro = caixa.top + caixa.height / 2 - window.innerHeight / 2;
      var desloc = Math.max(-26, Math.min(26, centro * -0.035));
      foto.style.transform = "translateY(" + desloc.toFixed(2) + "px)";
    }
    agendado = false;
  }

  window.addEventListener("scroll", function () {
    if (!agendado) { agendado = true; requestAnimationFrame(aoRolar); }
  }, { passive: true });
  window.addEventListener("resize", aoRolar, { passive: true });
  aoRolar();
})();
