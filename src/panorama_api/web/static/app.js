"use strict";
/*
 * Base única de JavaScript do front do Panorama Escola (cards t_71b25279 e
 * t_ee9b1eec). Sem dependência, sem bundler e sob CSP estrita: nada de eval,
 * markup por string ou escrita direta no documento — markup novo vem do
 * servidor. Progressivo: a página funciona sem este arquivo; `iniciar(raiz)`
 * é idempotente e blocos inseridos depois do load chamam `iniciar(bloco)`.
 */
(function (global, documento) {
  var iniciadores = [];
  var visitadas = new WeakSet();
  function registrar(fn) {
    if (typeof fn === "function" && iniciadores.indexOf(fn) === -1) iniciadores.push(fn);
    return fn;
  }
  function iniciar(raiz) {
    var alvo = raiz || documento;
    if (!alvo || !alvo.nodeType || visitadas.has(alvo)) return alvo;
    visitadas.add(alvo);
    iniciadores.forEach(function (iniciador) { iniciador(alvo); });
    return alvo;
  }

  /* Tabela completa ordenável (t_ee9b1eec): só `table[data-ordenavel]` e
     colunas com `data-tipo`; o botão do cabeçalho nasce aqui. O valor vem de
     `data-valor` (bruto, ponto decimal), nunca do texto: "1.234,5" não é
     número. Vazio vai sempre ao fim nos dois sentidos e `data-fixa` não se
     move: a ordenação é dentro de cada `<tbody>`, o grupo da linha. */
  function bruto(linha, coluna) {
    var celula = linha.cells[coluna];
    return celula ? celula.getAttribute("data-valor") || "" : "";
  }
  function comparar(tipo, sentido) {
    return function (a, b) {
      if (a.v === "" || b.v === "") {
        return a.v === b.v ? a.i - b.i : a.v === "" ? 1 : -1;
      }
      var ordem =
        tipo === "numero" ? Number(a.v) - Number(b.v) : a.v.localeCompare(b.v, "pt-BR");
      return ordem === 0 ? a.i - b.i : ordem * sentido;
    };
  }
  function permutar(corpo, coluna, ordem) {
    var linhas = [];
    var livres = [];
    for (var j = 0; j < corpo.rows.length; j += 1) {
      var linha = corpo.rows[j];
      var fixa = linha.hasAttribute("data-fixa");
      linhas.push({ no: linha, v: fixa ? "" : bruto(linha, coluna), i: j, fixa: fixa });
      if (!fixa) livres.push(linhas[j]);
    }
    livres.sort(ordem);
    var fila = livres.length - 1;
    var proximo = null;
    for (j = linhas.length - 1; j >= 0; j -= 1) {
      var alvo = linhas[j].fixa ? linhas[j].no : livres[fila--].no;
      corpo.insertBefore(alvo, proximo);
      proximo = alvo;
    }
  }
  function ordenar(tabela, th) {
    var tipo = th.getAttribute("data-tipo");
    var atual = th.getAttribute("aria-sort");
    // Primeiro clique: número desce (maior primeiro), texto sobe.
    var sentido = atual === "ascending" ? -1 : atual === "descending" ? 1 : tipo === "numero" ? -1 : 1;
    var ordem = comparar(tipo, sentido);
    for (var i = 0; i < tabela.tBodies.length; i += 1) {
      permutar(tabela.tBodies[i], th.cellIndex, ordem);
    }
    var colunas = tabela.querySelectorAll("thead th[data-tipo]");
    for (i = 0; i < colunas.length; i += 1) {
      colunas[i].removeAttribute("aria-sort");
    }
    th.setAttribute("aria-sort", sentido === 1 ? "ascending" : "descending");
  }
  function clique(ev) {
    var th = ev.target.closest("th[data-tipo]");
    if (th) ordenar(ev.currentTarget, th);
  }
  registrar(function ordenarTabelas(raiz) {
    var tabelas = raiz.querySelectorAll("table[data-ordenavel]");
    for (var i = 0; i < tabelas.length; i += 1) {
      if (tabelas[i].querySelector("thead button")) continue;
      var colunas = tabelas[i].querySelectorAll("thead th[data-tipo]");
      for (var j = 0; j < colunas.length; j += 1) {
        var botao = documento.createElement("button");
        botao.type = "button";
        botao.textContent = colunas[j].textContent.trim();
        colunas[j].textContent = "";
        colunas[j].appendChild(botao);
      }
      tabelas[i].addEventListener("click", clique);
    }
  });

  global.Panorama = global.Panorama || {};
  global.Panorama.iniciar = iniciar;
  global.Panorama.registrar = registrar;
  documento.addEventListener("DOMContentLoaded", function () {
    iniciar(documento);
  });
})(window, document);
