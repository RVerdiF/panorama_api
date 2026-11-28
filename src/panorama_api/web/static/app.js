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
     colunas com `data-tipo`; o botão do cabeçalho nasce aqui — salvo no
     índice, cujo SSR já emite o botão literal do protótipo (com o `span`
     da seta). O valor vem de
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
      // Como no `iniciarOrdenacao` do protótipo: quem perde a ordem tem o
      // `span` da seta esvaziado (o vazio esconde a seta pelo CSS).
      var antiga = colunas[i].querySelector("button span");
      if (antiga) antiga.textContent = "";
    }
    th.setAttribute("aria-sort", sentido === 1 ? "ascending" : "descending");
    // Espelha a direção na seta do protótipo (`th.ordenavel button span`,
    // literal no SSR do índice) com os glifos do design: `▲`/`▼` no ativo.
    var seta = th.querySelector("button span");
    if (seta) seta.textContent = sentido === 1 ? "▲" : "▼";
  }
  function clique(ev) {
    var th = ev.target.closest("th[data-tipo]");
    if (th) ordenar(ev.currentTarget, th);
  }
  registrar(function ordenarTabelas(raiz) {
    var tabelas = raiz.querySelectorAll("table[data-ordenavel]");
    for (var i = 0; i < tabelas.length; i += 1) {
      var tabela = tabelas[i];
      var colunas = tabela.querySelectorAll("thead th[data-tipo]");
      for (var j = 0; j < colunas.length; j += 1) {
        // O índice já traz o botão literal do protótipo no SSR (com o
        // `span` da seta): aí não há nada a criar, só a ligar abaixo.
        if (colunas[j].querySelector("button")) continue;
        var botao = documento.createElement("button");
        botao.type = "button";
        botao.textContent = colunas[j].textContent.trim();
        colunas[j].textContent = "";
        colunas[j].appendChild(botao);
      }
      // Trava de idempotência: ligar o clique mesmo quando o SSR já
      // emitiu os botões, uma única vez por tabela.
      if (tabela.getAttribute("data-ordenacao-pronta") !== "true") {
        tabela.setAttribute("data-ordenacao-pronta", "true");
        tabela.addEventListener("click", clique);
      }
    }
  });

  /* Barras de share (card V2 `t_cbd54a92`, rodada 1 item 1): o SSR emite
     `data-largura="X%"` no `.barra-share__preenche` e este iniciador aplica
     via CSSOM (`el.style.width`), que a CSP `style-src 'self'` permite — o
     atributo `style="width:…"` era descartado pelo navegador e nenhuma barra
     ganhava largura em produção. Sem este JS, a barra fica vazia e o número
     ao lado continua legível: ausência de largura, nunca largura errada. */
  registrar(function aplicarBarras(raiz) {
    var barras = raiz.querySelectorAll
      ? raiz.querySelectorAll(".barra-share__preenche[data-largura], .comp-preenche[data-largura], .cela-barra__preenche[data-largura]")
      : [];
    for (var i = 0; i < barras.length; i += 1) {
      var largura = barras[i].getAttribute("data-largura") || "";
      if (/^[0-9]+(\.[0-9]+)?%$/.test(largura)) barras[i].style.width = largura;
    }
  });

  /* Gráfico da série de matrículas (card V2 `t_cbd54a92`): linha com área,
     portado do protótipo (`panorama-design/assets/js/app.js`: `px`/`py`,
     `medir`/`desenhar`, `posicionarTip`/`ativar`/`maisProximo`, ponteiro,
     teclado setas/Home/End/Escape e `ResizeObserver` com debounce).
     Os dados vêm do SSR, nunca de mock: primeiro de uma ilha JSON
     (`<script type="application/json">` com `{"anos": [...], "valores": [...]}`,
     nulos onde não há dado) dentro da mesma `section#serie`; sem ilha, da
     tabela SSR da seção (ano no `th` e matrícula no primeiro `td.num`,
     ambos lidos como texto). Sem dados, não faz nada: o SVG do
     servidor (ou o "sem dado") continua valendo. Todo o SVG nasce de
     `createElementNS` e `textContent` — nenhuma escrita de marcação por
     string (CSP estrita) — e
     a caixa de leitura tem `aria-live="polite"`. */
  var SVG_NS = "http://www.w3.org/2000/svg";
  function numeroBR(casas) {
    return new Intl.NumberFormat("pt-BR", {
      minimumFractionDigits: casas || 0,
      maximumFractionDigits: casas || 0
    });
  }
  function inteiroOuNulo(v) {
    return v === null || v === undefined ? null : numeroBR(0).format(v);
  }
  function variacaoAnual(serie, i) {
    if (i <= 0) return null;
    var atual = serie[i];
    var anterior = serie[i - 1];
    if (atual === null || anterior === null || !anterior) return null;
    return ((atual - anterior) / anterior) * 100;
  }
  function numeroPtBR(texto) {
    var limpo = String(texto).trim();
    if (limpo === "" || /sem dado/i.test(limpo)) return null;
    var n = Number(limpo.replace(/\./g, "").replace(",", "."));
    return isFinite(n) ? n : null;
  }
  function serieDaIlha(secao) {
    var ilha = secao.querySelector('script[type="application/json"]');
    if (!ilha) return null;
    var dado;
    try {
      dado = JSON.parse(ilha.textContent);
    } catch (erro) {
      return null;
    }
    if (!dado || typeof dado !== "object") return null;
    var anos = dado.anos;
    var valores = dado.valores || dado.serie;
    if (!anos || !valores || !anos.length || anos.length !== valores.length) return null;
    return { anos: anos, valores: valores };
  }
  function serieDaTabela(secao) {
    var linhas = secao.querySelectorAll("table tbody tr");
    if (!linhas.length) return null;
    var anos = [];
    var valores = [];
    for (var i = 0; i < linhas.length; i += 1) {
      var anoCel = linhas[i].querySelector("th");
      var valorCel = linhas[i].querySelector("td.num");
      if (!anoCel || !valorCel) return null;
      var m = (anoCel.textContent || "").match(/(\d{4})/);
      if (!m) return null;
      anos.push(Number(m[1]));
      valores.push(numeroPtBR(valorCel.textContent || ""));
    }
    return { anos: anos, valores: valores };
  }
  function el(tag, attrs, texto) {
    var no = documento.createElementNS(SVG_NS, tag);
    if (attrs) {
      for (var chave in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, chave)) no.setAttribute(chave, attrs[chave]);
      }
    }
    if (texto !== undefined && texto !== null) no.textContent = texto;
    return no;
  }
  registrar(function graficoSerie(raiz) {
    var secoes = raiz.querySelectorAll ? raiz.querySelectorAll("section#serie div.grafico") : [];
    for (var s = 0; s < secoes.length; s += 1) {
      desenharSerie(secoes[s]);
    }
  });
  function desenharSerie(caixa) {
    if (!caixa || caixa.getAttribute("data-grafico-pronto") === "true") return;
    var secao = caixa.closest ? caixa.closest("section#serie") : null;
    if (!secao) return;
    var dados = serieDaIlha(secao) || serieDaTabela(secao);
    if (!dados) return;
    var anos = dados.anos;
    var serie = dados.valores;
    var n = serie.length;
    if (!anos || n < 2 || anos.length !== n) return;
    var temDado = false;
    for (var v = 0; v < n; v += 1) {
      if (serie[v] !== null) { temDado = true; break; }
    }
    if (!temDado) return;
    var validos = [];
    for (v = 0; v < n; v += 1) {
      if (serie[v] !== null) validos.push(serie[v]);
    }
    var maxV = Math.max.apply(null, validos) * 1.08;
    var minV = Math.min.apply(null, validos) * 0.86;
    var spanV = maxV - minV || 1;
    var ativoIdx = -1;
    var ativarPonto = null;
    var pontos = [];
    var dim = { W: 780, H: 320, PL: 84, PR: 28, PT: 28, PB: 58 };
    function px(i) { return dim.PL + (i * (dim.W - dim.PL - dim.PR)) / (n - 1); }
    function py(val) { return dim.PT + (1 - (val - minV) / spanV) * (dim.H - dim.PT - dim.PB); }
    function medir() {
      var largura = caixa.clientWidth || 780;
      var estreito = largura < 560;
      dim.W = Math.max(280, Math.round(largura));
      dim.H = estreito ? 258 : 320;
      dim.PL = estreito ? 54 : 84;
      dim.PR = estreito ? 14 : 28;
      dim.PT = estreito ? 22 : 28;
      dim.PB = estreito ? 46 : 58;
    }
    function desenhar() {
      medir();
      var W = dim.W, H = dim.H, PL = dim.PL, PR = dim.PR, PT = dim.PT, PB = dim.PB;
      var estreito = W < 560;
      pontos = [];
      for (var i = 0; i < n; i += 1) {
        if (serie[i] !== null) pontos.push([px(i), py(serie[i]), serie[i], i]);
      }
      if (!pontos.length) return;
      caixa.textContent = "";
      var svg = el("svg", {
        viewBox: "0 0 " + W + " " + H,
        width: String(W),
        height: String(H),
        role: "img",
        tabindex: "0",
        "aria-label": "Série de matrículas de " + anos[0] + " a " + anos[n - 1] +
          ". Use as setas do teclado para ler ano a ano."
      });
      var grupoGrades = el("g");
      var passos = estreito ? 2 : 3;
      for (var g = 0; g <= passos; g += 1) {
        var vv = minV + (spanV * g) / passos;
        var yy = py(vv);
        grupoGrades.appendChild(el("line", {
          class: "grafico__grade", x1: String(PL), y1: yy.toFixed(1),
          x2: String(W - PR), y2: yy.toFixed(1)
        }));
        grupoGrades.appendChild(el("text", { x: String(PL - 10), y: (yy + 5).toFixed(1), "text-anchor": "end" },
          inteiroOuNulo(Math.round(vv))));
      }
      svg.appendChild(grupoGrades);
      var linha = "";
      for (var k = 0; k < pontos.length; k += 1) {
        linha += (k === 0 ? "M" : "L") + pontos[k][0].toFixed(1) + "," + pontos[k][1].toFixed(1);
      }
      var area = linha + " L" + pontos[pontos.length - 1][0].toFixed(1) + "," + (H - PB) +
        " L" + pontos[0][0].toFixed(1) + "," + (H - PB) + " Z";
      svg.appendChild(el("path", { class: "grafico__area", d: area }));
      svg.appendChild(el("path", { class: "grafico__linha", d: linha }));
      var grupoGuia = el("g", { class: "grafico__guia-grupo", "aria-hidden": "true" });
      var guia = el("line", { class: "grafico__guia", hidden: "" });
      var halo = el("circle", { class: "grafico__halo", r: "0", hidden: "" });
      grupoGuia.appendChild(guia);
      grupoGuia.appendChild(halo);
      svg.appendChild(grupoGuia);
      for (k = 0; k < pontos.length; k += 1) {
        svg.appendChild(el("circle", {
          class: "grafico__ponto", "data-ponto": String(k),
          "data-ativo": k === ativoIdx ? "true" : "false",
          cx: pontos[k][0].toFixed(1), cy: pontos[k][1].toFixed(1),
          r: k === ativoIdx ? "5.5" : "4"
        }));
      }
      var ultimoP = pontos[pontos.length - 1];
      var rotuloFinal = el("text", {
        class: "grafico__rotulo",
        x: (ultimoP[0] - 10).toFixed(1), y: (ultimoP[1] - 16).toFixed(1), "text-anchor": "end"
      }, inteiroOuNulo(ultimoP[2]));
      if (ativoIdx === pontos.length - 1) rotuloFinal.setAttribute("hidden", "");
      svg.appendChild(rotuloFinal);
      var grupoEixos = el("g", { class: "grafico__eixos" });
      for (i = 0; i < n; i += 1) {
        grupoEixos.appendChild(el("text", {
          x: px(i).toFixed(1), y: String(H - PB + (estreito ? 24 : 28)), "text-anchor": "middle"
        }, String(anos[i])));
      }
      svg.appendChild(grupoEixos);
      svg.appendChild(el("rect", {
        class: "grafico__captura", x: String(PL - 16), y: String(PT - 14),
        width: String(W - PL - PR + 34), height: String(H - PT - PB + 28)
      }));
      caixa.appendChild(svg);
      var tip = documento.createElement("div");
      tip.setAttribute("class", "grafico__tip");
      tip.setAttribute("aria-live", "polite");
      tip.hidden = true;
      var tipAno = documento.createElement("p");
      tipAno.setAttribute("class", "grafico__tip-ano");
      var tipValor = documento.createElement("p");
      tipValor.setAttribute("class", "grafico__tip-valor");
      var tipVar = documento.createElement("p");
      tipVar.setAttribute("class", "grafico__tip-var");
      tip.appendChild(tipAno);
      tip.appendChild(tipValor);
      tip.appendChild(tipVar);
      caixa.appendChild(tip);
      caixa.setAttribute("data-grafico-pronto", "true");
      ligar(svg, guia, halo, tip, tipAno, tipValor, tipVar, rotuloFinal);
      if (ativoIdx > -1 && ativarPonto) ativarPonto(ativoIdx);
    }
    function posicionarTip(svg, tip, p) {
      var r = svg.getBoundingClientRect();
      var escala = r.width / dim.W || 1;
      var x = p[0] * escala;
      var y = p[1] * escala;
      tip.hidden = false;
      var largura = tip.offsetWidth;
      var altura = tip.offsetHeight;
      var esq = Math.min(Math.max(x, largura / 2 + 2), r.width - largura / 2 - 2);
      tip.style.left = esq + "px";
      if (y - altura - 14 < 0) {
        tip.dataset.pos = "baixo";
        tip.style.top = Math.min(y + 18, r.height - altura) + "px";
      } else {
        tip.dataset.pos = "cima";
        tip.style.top = (y - 14) + "px";
      }
    }
    function limpar(svg, guia, halo, tip, rotuloFinal) {
      ativoIdx = -1;
      guia.setAttribute("hidden", "");
      halo.setAttribute("hidden", "");
      tip.hidden = true;
      var circulos = svg.querySelectorAll(".grafico__ponto");
      for (var i = 0; i < circulos.length; i += 1) {
        circulos[i].dataset.ativo = "false";
        circulos[i].setAttribute("r", "4");
      }
      if (rotuloFinal) rotuloFinal.removeAttribute("hidden");
    }
    function ligar(svg, guia, halo, tip, tipAno, tipValor, tipVar, rotuloFinal) {
      ativarPonto = ativar;
      function ativar(k) {
        var p = pontos[k];
        if (!p) return;
        ativoIdx = k;
        guia.removeAttribute("hidden");
        guia.setAttribute("x1", p[0].toFixed(1));
        guia.setAttribute("x2", p[0].toFixed(1));
        guia.setAttribute("y1", p[1].toFixed(1));
        guia.setAttribute("y2", (dim.H - dim.PB).toFixed(1));
        halo.removeAttribute("hidden");
        halo.setAttribute("cx", p[0].toFixed(1));
        halo.setAttribute("cy", p[1].toFixed(1));
        halo.setAttribute("r", "9");
        var circulos = svg.querySelectorAll(".grafico__ponto");
        for (var i = 0; i < circulos.length; i += 1) {
          circulos[i].dataset.ativo = i === k ? "true" : "false";
          circulos[i].setAttribute("r", i === k ? "5.5" : "4");
        }
        if (rotuloFinal) {
          if (k === pontos.length - 1) rotuloFinal.setAttribute("hidden", "");
          else rotuloFinal.removeAttribute("hidden");
        }
        var va = variacaoAnual(serie, p[3]);
        tipAno.textContent = String(anos[p[3]]);
        tipValor.textContent = inteiroOuNulo(p[2]) + " matrículas";
        if (va === null) tipVar.textContent = "Primeiro ano do recorte";
        else tipVar.textContent = (va >= 0 ? "▲ +" : "▼ −") + numeroBR(1).format(Math.abs(va)) +
          "% sobre " + anos[p[3] - 1];
        tip.dataset.sinal = va === null ? "neutro" : va >= 0 ? "pos" : "neg";
        posicionarTip(svg, tip, p);
      }
      function maisProximo(clientX) {
        var r = svg.getBoundingClientRect();
        var xUser = ((clientX - r.left) / r.width) * dim.W;
        var melhor = 0, dist = Infinity;
        for (var k = 0; k < pontos.length; k += 1) {
          var d = Math.abs(pontos[k][0] - xUser);
          if (d < dist) { dist = d; melhor = k; }
        }
        return melhor;
      }
      svg.addEventListener("pointermove", function (ev) { ativar(maisProximo(ev.clientX)); });
      svg.addEventListener("pointerdown", function (ev) { ativar(maisProximo(ev.clientX)); });
      svg.addEventListener("pointerleave", function (ev) { if (ev.pointerType === "mouse") limpar(svg, guia, halo, tip, rotuloFinal); });
      svg.addEventListener("focus", function () { ativar(pontos.length - 1); });
      svg.addEventListener("blur", function () { limpar(svg, guia, halo, tip, rotuloFinal); });
      svg.addEventListener("keydown", function (ev) {
        var k = ativoIdx < 0 ? pontos.length - 1 : ativoIdx;
        if (ev.key === "ArrowRight" || ev.key === "ArrowDown") { ev.preventDefault(); ativar(Math.min(k + 1, pontos.length - 1)); }
        else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") { ev.preventDefault(); ativar(Math.max(k - 1, 0)); }
        else if (ev.key === "Home") { ev.preventDefault(); ativar(0); }
        else if (ev.key === "End") { ev.preventDefault(); ativar(pontos.length - 1); }
        else if (ev.key === "Escape") { ev.preventDefault(); limpar(svg, guia, halo, tip, rotuloFinal); }
      });
    }
    desenhar();
    var larguraAnterior = caixa.clientWidth;
    var tRedesenho = null;
    function reagendar() {
      clearTimeout(tRedesenho);
      tRedesenho = setTimeout(desenhar, 90);
    }
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(function () {
        var l = caixa.clientWidth;
        if (!l || Math.abs(l - larguraAnterior) < 2) return;
        larguraAnterior = l;
        reagendar();
      });
      ro.observe(caixa);
    } else {
      window.addEventListener("resize", function () {
        clearTimeout(tRedesenho);
        tRedesenho = setTimeout(desenhar, 120);
      });
    }
  }

  /* Busca `/app/` (card V3 `t_9f384f60`): combobox progressiva de município
     + validação no cliente, portadas do protótipo (`assets/js/app.js`:
     `iniciarCombobox` e `avisar`). O SSR emite o `select#municipio`
     funcionando sem JS; aqui ele é escondido (sem `name`, para não duplicar
     o parâmetro) e vira `div.combo` — `input` visível sem `name`, `hidden`
     com o código e a lista — alimentada pela ilha JSON `dados-municipios`
     (`[nome, codigo]`). `q` com 1–2 caracteres e "Ver mercado do município"
     sem município escolhido mostram a mensagem em `p.retorno` e não
     submetem; o servidor continua validando (422 inalterado). */
  function normalizarBusca(texto) {
    return String(texto).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }
  function lerIlhaMunicipios() {
    var ilha = documento.getElementById("dados-municipios");
    if (!ilha) return [];
    try {
      var dado = JSON.parse(ilha.textContent);
      if (dado && Object.prototype.toString.call(dado) === "[object Array]") return dado;
    } catch (erro) { /* sem ilha a combobox abre vazia */ }
    return [];
  }
  function avisarBusca(retorno, msg) {
    if (!retorno) return;
    retorno.textContent = msg;
    retorno.hidden = false;
  }
  function ligarCombobox(campo, lista, seta, pares, oculto) {
    var filtrados = [];
    var ativo = -1;
    var suprimirAbertura = false;
    function abrir(filtro) {
      var alvo = normalizarBusca(filtro || "");
      filtrados = [];
      for (var i = 0; i < pares.length && filtrados.length < 60; i += 1) {
        if (alvo === "" || normalizarBusca(pares[i][0]).indexOf(alvo) > -1) {
          filtrados.push(pares[i]);
        }
      }
      while (lista.firstChild) lista.removeChild(lista.firstChild);
      if (!filtrados.length) {
        var vazio = documento.createElement("li");
        vazio.className = "vazio";
        vazio.textContent = "Nenhum município com esse trecho.";
        lista.appendChild(vazio);
      } else {
        filtrados.forEach(function (par, i) {
          var li = documento.createElement("li");
          li.setAttribute("role", "option");
          li.dataset.idx = String(i);
          var nome = documento.createElement("span");
          nome.textContent = par[0];
          var cod = documento.createElement("span");
          cod.textContent = par[1];
          li.appendChild(nome);
          li.appendChild(cod);
          li.addEventListener("mousedown", function (ev) {
            ev.preventDefault();
            escolher(i);
          });
          lista.appendChild(li);
        });
      }
      ativo = -1;
      lista.dataset.aberta = "true";
      campo.setAttribute("aria-expanded", "true");
    }
    function fechar() {
      lista.dataset.aberta = "false";
      campo.setAttribute("aria-expanded", "false");
      ativo = -1;
    }
    function escolher(i) {
      var par = filtrados[i];
      if (!par) return;
      oculto.value = par[1];
      campo.value = par[0];
      fechar();
      suprimirAbertura = true;
      campo.focus();
      setTimeout(function () { suprimirAbertura = false; }, 0);
    }
    function destacar() {
      var itens = lista.querySelectorAll("li[data-idx]");
      for (var k = 0; k < itens.length; k += 1) {
        var ligado = Number(itens[k].dataset.idx) === ativo;
        itens[k].setAttribute("aria-selected", ligado ? "true" : "false");
        if (ligado) {
          var topo = itens[k].offsetTop;
          if (topo < lista.scrollTop) lista.scrollTop = topo;
          else if (topo + itens[k].offsetHeight > lista.scrollTop + lista.clientHeight) {
            lista.scrollTop = topo + itens[k].offsetHeight - lista.clientHeight;
          }
        }
      }
    }
    campo.addEventListener("focus", function () { if (!suprimirAbertura) abrir(""); });
    campo.addEventListener("input", function () { oculto.value = ""; abrir(campo.value); });
    if (seta) {
      seta.addEventListener("click", function () {
        if (lista.dataset.aberta === "true") fechar();
        else { campo.focus(); abrir(campo.value); }
      });
    }
    campo.addEventListener("keydown", function (ev) {
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        if (lista.dataset.aberta !== "true") { abrir(campo.value); return; }
        ativo = ev.key === "ArrowDown"
          ? Math.min(ativo + 1, filtrados.length - 1)
          : Math.max(ativo - 1, 0);
        destacar();
      } else if (ev.key === "Enter" && lista.dataset.aberta === "true" && ativo > -1) {
        ev.preventDefault();
        escolher(ativo);
      } else if (ev.key === "Escape") {
        fechar();
      }
    });
    documento.addEventListener("mousedown", function (ev) {
      if (!ev.target.closest(".combo")) fechar();
    });
  }
  function montarComboBusca(form) {
    // A combobox do protótipo já vem no SSR (`input#co_municipio`,
    // `button#botao-municipio`, `ul#lista-municipios`); o `hidden` com o
    // código chega desabilitado (sem JS quem envia é o `select` do
    // `noscript`) e só passa a valer aqui, quando a lista está ligada.
    var campo = form.querySelector("input#co_municipio");
    var lista = form.querySelector("ul#lista-municipios");
    var seta = form.querySelector("button#botao-municipio");
    var oculto = form.querySelector("input[data-combo-codigo]");
    if (!campo || !lista || !oculto) return null;
    oculto.disabled = false;
    ligarCombobox(campo, lista, seta, lerIlhaMunicipios(), oculto);
    return oculto;
  }
  /* Ordenação da busca no servidor (card `t_6a9f6b6f`): o clique no
     `th.ordenavel button` segue a regra do protótipo (`ligarOrdenacao`:
     coluna em `ascending` vira `descending`, qualquer outra vira
     `ascending`) e navega para a mesma URL com `ordem`/`direcao`, voltando à
     1ª página. A ordem é aplicada pelo SQL, não reordenando a página. */
  function ligarOrdenacaoBusca(tabela) {
    if (!tabela || tabela.getAttribute("data-ordenacao-pronta") === "true") return;
    tabela.setAttribute("data-ordenacao-pronta", "true");
    var botoes = tabela.querySelectorAll("th.ordenavel button");
    for (var b = 0; b < botoes.length; b += 1) {
      botoes[b].addEventListener("click", function (ev) {
        var th = ev.currentTarget.closest("th");
        if (!th || !th.dataset.campo) return;
        var direcao = th.getAttribute("aria-sort") === "ascending" ? "desc" : "asc";
        var destino = new URL(window.location.href);
        destino.searchParams.set("ordem", th.dataset.campo);
        destino.searchParams.set("direcao", direcao);
        destino.searchParams.delete("offset");
        window.location.assign(destino.toString());
      });
    }
  }
  function prepararBusca(form) {
    if (!form || form.getAttribute("data-busca-pronta") === "true") return;
    form.setAttribute("data-busca-pronta", "true");
    var retorno = form.querySelector("p#retorno");
    var campoQ = form.querySelector("input#q");
    var botaoMercado = form.querySelector("button#ir-mercado");
    var oculto = montarComboBusca(form);
    form.addEventListener("submit", function (ev) {
      var nome = campoQ ? campoQ.value.trim() : "";
      if (nome.length > 0 && nome.length < 3) {
        ev.preventDefault();
        avisarBusca(retorno, "O nome precisa ter ao menos 3 caracteres.");
        if (campoQ) campoQ.focus();
        return;
      }
      var vaiAoMercado = !!botaoMercado && ev.submitter === botaoMercado;
      if (vaiAoMercado && (!oculto || !oculto.value)) {
        ev.preventDefault();
        avisarBusca(retorno, "Escolha um município na lista para abrir o mercado dele.");
      }
    });
  }
  registrar(function buscaProgressiva(raiz) {
    var formularios = raiz.querySelectorAll ? raiz.querySelectorAll("form#form-busca") : [];
    for (var f = 0; f < formularios.length; f += 1) {
      prepararBusca(formularios[f]);
    }
    var tabelaBusca = raiz.querySelector ? raiz.querySelector("table#tabela-resultados") : null;
    if (tabelaBusca && documento.getElementById("form-busca")) ligarOrdenacaoBusca(tabelaBusca);
  });

  /* Índice de municípios (`#indice-municipios`): filtro progressivo por nome
     (cards D1-E4a e V4-I). O SSR entrega a tabela completa (853 linhas) e este
     iniciador só refina: normaliza com `normalizarBusca` (NFD sem
     diacríticos + minúsculas), alterna `hidden` nas linhas e atualiza a
     contagem em `p#retorno-municipios` com a copy do protótipo
     (`assets/js/app.js` do design, `iniciarMunicipios`), sem o trecho de
     mock. Sem filtro ou lista vazia, o estado vazio do
     design entra como `tr > td[colspan] > div.estado-vazio` ("Nenhum
     município com esse nome"); o `style=` inline do design vira regra no
     `app.css` (CSP `style-src 'self'`). Sem JS a lista continua completa.
     A coluna do nome sai do cabeçalho (o 4b tem `#` antes do nome): procura
     o `th` "Município" em vez de fixar o índice da célula. */
  registrar(function filtrarIndice(raiz) {
    var caixa = null;
    if (!raiz || !raiz.querySelector) return;
    if (raiz.id === "indice-municipios") caixa = raiz;
    else caixa = raiz.querySelector("#indice-municipios");
    if (!caixa || caixa.getAttribute("data-filtro-pronto") === "true") return;
    var campo = caixa.querySelector("input#filtro-municipio");
    var retorno = caixa.querySelector("p#retorno-municipios");
    var linhas = caixa.querySelectorAll("table#tabela-municipios tbody tr");
    if (!campo || !retorno || !linhas.length) return;
    caixa.setAttribute("data-filtro-pronto", "true");
    var colunaNome = 0;
    var cabecalhos = caixa.querySelectorAll("table#tabela-municipios thead th");
    for (var k = 0; k < cabecalhos.length; k += 1) {
      // O `th` do 4b traz o botão literal do protótipo ("Município ↑…"):
      // casa pelo nome no início do texto, não pela igualdade.
      if (cabecalhos[k].textContent.trim().indexOf("Município") === 0) colunaNome = cabecalhos[k].cellIndex;
    }
    var total = linhas.length;
    var nomes = [];
    for (var i = 0; i < linhas.length; i += 1) {
      nomes.push(normalizarBusca(linhas[i].cells[colunaNome] ? linhas[i].cells[colunaNome].textContent : ""));
    }
    // Linha do estado vazio do protótipo, montada uma vez e anexada ao
    // `tbody` só quando o filtro zera; `colspan` cobre as colunas do
    // cabeçalho (7 no 4b, 2 no 4a degradado).
    var vazio = null;
    function linhaVazia(corpo) {
      if (vazio && vazio.parentNode === corpo) return vazio;
      vazio = documento.createElement("tr");
      var celula = documento.createElement("td");
      celula.setAttribute("colspan", String(cabecalhos.length));
      var estado = documento.createElement("div");
      estado.setAttribute("class", "estado-vazio");
      var titulo = documento.createElement("h3");
      titulo.textContent = "Nenhum município com esse nome";
      var dica = documento.createElement("p");
      dica.textContent = "O índice cobre " + total + " municípios. Tente parte do nome, sem acento.";
      estado.appendChild(titulo);
      estado.appendChild(dica);
      celula.appendChild(estado);
      vazio.appendChild(celula);
      return vazio;
    }
    campo.addEventListener("input", function () {
      var q = campo.value;
      var termo = normalizarBusca(q.trim());
      var visiveis = 0;
      for (var j = 0; j < linhas.length; j += 1) {
        var mostra = termo === "" || nomes[j].indexOf(termo) !== -1;
        linhas[j].hidden = !mostra;
        if (mostra) visiveis += 1;
      }
      var corpo = caixa.querySelector("table#tabela-municipios tbody");
      if (!corpo) return;
      if (visiveis === 0) {
        corpo.appendChild(linhaVazia(corpo));
      } else if (vazio && vazio.parentNode) {
        vazio.parentNode.removeChild(vazio);
      }
      if (termo === "") {
        retorno.textContent = total + " municípios no recorte";
      } else {
        retorno.textContent = visiveis + (visiveis === 1 ? " município encontrado" : " municípios encontrados") + " para \u201c" + q + "\u201d";
      }
    });
  });

  global.Panorama = global.Panorama || {};
  global.Panorama.iniciar = iniciar;
  global.Panorama.registrar = registrar;
  documento.addEventListener("DOMContentLoaded", function () {
    iniciar(documento);
  });
})(window, document);
