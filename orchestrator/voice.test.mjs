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
});
