// Condition script for the calendar reminder.
//
// Fires once per appointment, LEAD_MINUTES before it starts. Announced ids are
// kept in trigger state so a restart, a re-evaluation, or a minute that ticks
// twice cannot repeat a reminder.
//
// Like the prayer trigger this only reads. State is capped at 16 KB, so the
// remembered list is trimmed rather than allowed to grow for the life of the job.
//
// Tools are called directly -- exec({...}), not tools.call('exec', {...}).
// The 2026.8.1 upgrade removed the `tools` global and this script failed five
// times running with "ReferenceError: tools is not defined" before anyone
// noticed. Doctor migrates the old idiom, but only from a script with no
// comments in it, so it left this one alone and said so in a preview nobody
// read. The returned shape did not change.

const LEAD_MINUTES = 15;
const REMEMBER = 40;

// "2026-09-01T14:30+02:00\tDentist" from calendar.sh list --iso. The offset is
// load-bearing: the calendar renders in Europe/Paris while this host runs on
// UTC, so a bare "14:30" parsed with the process locale is two hours wrong.
// All-day entries carry a literal "allday" field and are skipped -- a reminder
// 15 minutes before midnight is not what "all day" means.
const LINE = /^(\S+T\d{2}:\d{2}[+\-]\d{2}:\d{2})\t(?!allday\t)(.+?)\s*$/;

const res = await exec({ command: 'calendar.sh list 1 --iso' });
const out = String(
  res?.result?.details?.aggregated ??
  res?.result?.details?.stdout ??
  res?.result?.stdout ??
  ''
);

const seen = Array.isArray(trigger.state?.announced) ? trigger.state.announced : [];
const now = Date.now();
const due = [];

for (const line of out.split('\n')) {
  const m = LINE.exec(line.replace(/\s+$/, ''));
  if (!m) continue;
  const [, iso, summary] = m;
  const startsAt = Date.parse(iso);
  if (Number.isNaN(startsAt)) continue;
  const minutesAway = (startsAt - now) / 60000;
  const id = `${iso}|${summary}`;
  if (minutesAway >= 0 && minutesAway <= LEAD_MINUTES && !seen.includes(id)) {
    // Rendered in the calendar's own zone, which is what the household reads
    // off a clock, not the host's.
    const hhmm = iso.slice(11, 16);
    due.push({ id, summary, hhmm, minutesAway: Math.round(minutesAway) });
  }
}

if (due.length === 0) {
  json({ fire: false, state: trigger.state ?? { announced: seen } });
} else {
  const parts = due.map((e) => `${e.summary} في ${e.hhmm}`).join(' و ');
  json({
    fire: true,
    message:
      `موعد قادم بعد ${due[0].minutesAway} دقيقة: ${parts}. ` +
      `ذكّر بذلك بجملة واحدة قصيرة بالعربية الفصحى، دون أي إضافات.`,
    state: { announced: [...seen, ...due.map((e) => e.id)].slice(-REMEMBER) },
  });
}
