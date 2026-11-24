"use strict";
/*
 * Base única de JavaScript do front do Panorama Escola (card t_71b25279).
 *
 * Sem dependência, sem bundler e sem CDN: este arquivo é servido pelo
 * AssetRegistry com hash do conteúdo e vive sob CSP estrita. Por isso nada de
 * avaliação dinâmica de código, injeção de markup por string, função construída
 * em runtime ou escrita direta no documento — markup novo vem do servidor,
 * nunca de string no cliente.
 *
 * Progressivo: a página funciona inteira sem este arquivo. A inicialização é
 * idempotente e recebe uma raiz — `Panorama.iniciar(raiz = document)`. Quem
 * melhora a página registra `Panorama.registrar(fn)`; um carregador que insira
 * blocos depois do load chama `Panorama.iniciar(bloco)` para aplicar os
 * inicializadores só naquele fragmento, sem reinicializar o resto.
 */
(function (global, documento) {
  var iniciadores = [];
  var visitadas = new WeakSet();

  function registrar(iniciador) {
    if (typeof iniciador === "function" && iniciadores.indexOf(iniciador) === -1) {
      iniciadores.push(iniciador);
    }
    return iniciador;
  }

  function iniciar(raiz) {
    var alvo = raiz || documento;
    if (!alvo || !alvo.nodeType || visitadas.has(alvo)) {
      return alvo;
    }
    visitadas.add(alvo);
    for (var i = 0; i < iniciadores.length; i += 1) {
      iniciadores[i](alvo);
    }
    return alvo;
  }

  global.Panorama = global.Panorama || {};
  global.Panorama.iniciar = iniciar;
  global.Panorama.registrar = registrar;

  documento.addEventListener("DOMContentLoaded", function () {
    iniciar(documento);
  });
})(window, document);
