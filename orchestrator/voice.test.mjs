import { test } from "node:test";
import assert from "node:assert/strict";

import { cleanTranscript, stripName } from "./transcript.mjs";

test("whisper noise labels and phantom endings are not requests", () => {
  assert.equal(cleanTranscript("[Music]"), "");
  assert.equal(cleanTranscript(" (silence) "), "");
  assert.equal(cleanTranscript("Thank you."), "");
  assert.equal(cleanTranscript("Thanks for watching!"), "");
  assert.equal(cleanTranscript("[Music]\nWhat time is it?"), "What time is it?");
  assert.equal(cleanTranscript("Thank you, add milk."), "Thank you, add milk.");
});

test("the wake word is dropped only from the front", () => {
  assert.equal(stripName("Abbes, what is on the shopping list?"), "what is on the shopping list?");
  assert.equal(stripName("Abbas play some jazz"), "play some jazz");
  assert.equal(stripName("Hey Abbas. Pause the music."), "Pause the music.");
  assert.equal(stripName("Abès, ajoute du lait."), "ajoute du lait.");
  assert.equal(stripName("Tell Abbas I said hi"), "Tell Abbas I said hi");
  assert.equal(stripName("Abbas"), "");
  assert.equal(stripName("Abbey Road by the Beatles"), "Abbey Road by the Beatles");
  assert.equal(stripName("Ebbes, what can you help me with?"), "what can you help me with?");
  assert.equal(stripName("Abs, what is on my shopping list?"), "what is on my shopping list?");
  assert.equal(stripName("Abs workout music please"), "Abs workout music please");
  assert.equal(stripName("Add eggs to the list"), "Add eggs to the list");
  assert.equal(stripName("Yes, add milk"), "Yes, add milk");
});

import { SpokenFilter, speakable } from "./transcript.mjs";
import { Chunker } from "./sentences.mjs";

function spoken(deltas, toolAfter = -1) {
  const out = [];
  const f = new SpokenFilter(Chunker, (s) => out.push(s));
  deltas.forEach((d, i) => { f.push(d); if (i === toolAfter) f.endParagraph(); });
  f.end();
  return out.join(" ");
}

test("the Arabic wake word and its vocative are dropped", () => {
  assert.equal(stripName("يا عباس، شنوة الوقت؟"), "شنوة الوقت؟");
  assert.equal(stripName("عبّاس زيد الصوت"), "زيد الصوت");
  assert.equal(stripName("شنوة الوقت؟"), "شنوة الوقت؟");
});

test("thinking out loud is not spoken, the answer is", () => {
  assert.equal(spoken(["The user said hello in a voice message. ", "It is just a greeting.\n\n", "Hi, how can I help?"]),
    "Hi, how can I help?");
  assert.equal(spoken(["Let me check the ", "shopping list first."], 1), "");
  assert.equal(spoken(["Sure. ", "I added milk to the list."]), "Sure. I added milk to the list.");
  assert.equal(spoken(["Okay, so the user wants music.\n\nPlaying jazz on the speaker now."]),
    "Playing jazz on the speaker now.");
});

test("Arabic script is never handed to the English voice", () => {
  assert.equal(speakable("You said \"شنوة\", which means what."), "You said , which means what.");
  assert.equal(speakable("شنوة الوقت؟"), "");
  assert.equal(speakable("⚠ tool failed"), "");
});
