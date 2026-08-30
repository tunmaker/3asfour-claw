// node orchestrator/sentences.test.mjs
import { Chunker, cut } from "./sentences.mjs";

let pass = 0, fail = 0;
function eq(got, want, label) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log(`  ok   ${label}`); }
  else { fail++; console.log(`  FAIL ${label}\n       got  ${g}\n       want ${w}`); }
}

// --- cut() ---
eq(cut("مرحبا. كيفك؟").sentences, ["مرحبا."], "cuts the complete sentence only");
eq(cut("مرحبا. كيفك؟").rest, "كيفك؟", "incomplete tail is carried, not spoken");
eq(cut("مرحبا. كيفك؟", { flush: true }).sentences, ["مرحبا.", "كيفك؟"], "flush emits both");
eq(cut("قداش 19:09.").sentences, [], "time not split, no trailing space yet");
eq(cut("قداش 19:09. ").sentences, ["قداش 19:09."], "time kept whole, cut after");
eq(cut("الثمن 3.5 دينار.").sentences, [], "decimal not split (incomplete tail)");
eq(cut("الثمن 3.5 دينار. ").sentences, ["الثمن 3.5 دينار."], "decimal survives, sentence cut");
eq(cut('قال "باهي." وخرج. ').sentences, ['قال "باهي."', "وخرج."], "closing quote absorbed");
eq(cut("باهي، نمشي للسوق وناخو خبز. ").sentences, ["باهي، نمشي للسوق وناخو خبز."],
   "arabic comma is NOT a cut point");
eq(cut("أول. ثاني! ثالث؟ ").sentences, ["أول.", "ثاني!", "ثالث؟"], "three terminators");
eq(cut("بلا نقطة").sentences, [], "no terminator, nothing emitted");
eq(cut("بلا نقطة", { flush: true }).sentences, ["بلا نقطة"], "flush emits the tail");

// --- Chunker over a delta stream ---
const c = new Chunker();
const out = [];
for (const d of ["قد", "اش ", "19:", "09.", " وفمّا ", "موعد", " غدوة؟", " باهي"]) {
  out.push(...c.push(d));
}
eq(out, ["قداش 19:09.", "وفمّا موعد غدوة؟"], "streamed deltas cut correctly");
eq(c.end(), ["باهي"], "end() flushes the tail");

// a model that never punctuates must still produce speech
const c2 = new Chunker({ softLimit: 60 });
const long = "كلمة ".repeat(40);
const emitted = c2.push(long);
eq(emitted.length > 0, true, "soft limit forces a cut without punctuation");
eq(emitted[0].endsWith(" "), false, "soft cut is trimmed");
eq(long.startsWith(emitted[0]), true, "soft cut does not split a word");

// replace semantics (chat delta with replace=true)
const c3 = new Chunker();
c3.push("خطأ");
c3.replace("صحيح. ");
eq(c3.end(), ["صحيح."], "replace discards the old buffer");

// --- first-chunk latency behaviour (added after measuring 11.4s to first audio) ---
{
  const c = new Chunker({ firstLimit: 70, softLimit: 180 });
  const preamble = "دعني أقرأ ملفي الشخصي لأخبرك من أنا وماذا أستطيع أن أفعل لك:";
  const first = c.push(preamble + " ");
  eq(first, [preamble], "colon ends the preamble — first audio does not wait for a full stop");
}
{
  const c = new Chunker({ firstLimit: 70, softLimit: 180 });
  const run = "أنا مساعد ذكي شغال فالدار، نعاونك فالنوتات، وفقائمة الشراء، وفالمواعيد، وفكل شي تحب عليه بلا ما نوقف";
  const out = c.push(run);
  eq(out.length >= 1, true, "an over-long run with no terminator still emits");
  eq(out[0].length <= 70, true, "first chunk respects the tighter first limit");
  eq(/[،,]$/.test(out[0]), true, "force cut lands on a comma, where a speaker breathes");
}
{
  const c = new Chunker({ firstLimit: 70, softLimit: 180 });
  c.push("قصيرة. ");
  const later = c.push("ب".repeat(120) + " ");
  eq(later.length === 0, true, "after the first chunk, 120 chars is under the larger limit");
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
