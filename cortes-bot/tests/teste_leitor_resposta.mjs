/* Lê o `lerResposta` direto do painel.html e confere que ele aguenta o que um chat devolve.
 *
 * O botão "Copiar prompt" existe para quem não tem credencial de IA: a pessoa cola o prompt
 * em qualquer chat e traz a resposta de volta. Cada chat responde de um jeito — com cercas,
 * em JSON mesmo sem pedirmos, com um "Claro! Aqui está" na frente — e o leitor tem que
 * aproveitar todos. Este teste é o que impede uma mexida no regex de quebrar isso calado.
 *
 *     node tests/teste_leitor_resposta.mjs
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const raiz = dirname(dirname(fileURLToPath(import.meta.url)));   // cortes-bot/
const html = readFileSync(join(raiz, "cortes", "painel.html"), "utf-8");
const js = html.slice(html.indexOf("<script>") + 8, html.lastIndexOf("</script>"));
const corpo = js.slice(js.indexOf("function lerResposta"));
const tags = s => s.split(/[\s,]+/).filter(Boolean);
const lerResposta = new Function("tags", corpo.slice(0, corpo.indexOf("\n}") + 2) + "\nreturn lerResposta;")(tags);

const ESPERADO = { titulo: "Fugiu da polícia", descricao: "Deu ruim.", hashtags: ["gta6", "alanzoka"] };
const casos = [
  ["o formato que pedimos", "Título: Fugiu da polícia\nDescrição: Deu ruim.\nHashtags: #gta6 #alanzoka", ESPERADO],
  ["dentro das cercas", "```\nTítulo: Fugiu da polícia\nDescrição: Deu ruim.\nHashtags: #gta6 #alanzoka\n```", ESPERADO],
  ["com conversa em volta", "Claro! Aqui está:\n\nTítulo: Fugiu da polícia\nDescrição: Deu ruim.\nHashtags: #gta6 #alanzoka\n\nEspero ter ajudado!", ESPERADO],
  ["título entre aspas", 'Título: "Fugiu da polícia"\nDescrição: Deu ruim.\nHashtags: #gta6 #alanzoka', ESPERADO],
  ["JSON sem pedirmos", '{"titulo": "Fugiu da polícia", "descricao": "Deu ruim.", "hashtags": ["gta6", "#alanzoka"]}', ESPERADO],
  ["JSON com chaves em inglês", '{"title": "Fugiu da polícia", "description": "Deu ruim.", "hashtags": "#gta6 #alanzoka"}', ESPERADO],
  ["JSON dentro das cercas", '```json\n{"titulo": "Fugiu da polícia", "descricao": "Deu ruim.", "hashtags": ["gta6", "alanzoka"]}\n```', ESPERADO],
  ["JSON mal formado, lido como linhas", '{"titulo": "Fugiu da polícia",, "descricao": "Deu ruim.", "hashtags": ["gta6", "alanzoka"]}', ESPERADO],
  ["sem hashtags", "Título: Fugiu da polícia\nDescrição: Deu ruim.",
   { ...ESPERADO, hashtags: [] }],
  ["resposta inútil", "Desculpe, não consigo ajudar com isso.",
   { titulo: "", descricao: "", hashtags: [] }],
];

let falhas = 0;
for (const [nome, entrada, esperado] of casos) {
  const obtido = lerResposta(entrada);
  const ok = JSON.stringify(obtido) === JSON.stringify(esperado);
  if (!ok) {
    falhas++;
    console.error(`FALHOU  ${nome}\n   esperado ${JSON.stringify(esperado)}\n   obtido   ${JSON.stringify(obtido)}`);
  } else {
    console.log(`ok      ${nome}`);
  }
}
console.log(falhas ? `\n${falhas} de ${casos.length} falharam.` : `\n${casos.length} casos, todos passaram.`);
process.exit(falhas ? 1 : 0);
