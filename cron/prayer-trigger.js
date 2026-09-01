// Condition script for the prayer-time announcement.
//
// Cron evaluates this every minute. It returns fire:false on all but a handful
// of minutes a day, and a false evaluation costs no model call and writes no
// run history -- which is the whole reason the announcement is a trigger rather
// than six scheduled jobs. Six jobs would also need re-deriving twice a year;
// this asks the calculation each time.
//
// The script only ever reads. Everything that changes the world belongs in the
// payload, because a payload that fails leaves the returned state unpersisted
// and the next evaluation is free to fire again.

const LEAD_MINUTES = 0;   // announce at the time itself, not before

const res = await tools.call('exec', { command: `prayer.sh next --minutes ${LEAD_MINUTES}` });
const out = String(
  res?.result?.details?.aggregated ??
  res?.result?.details?.stdout ??
  res?.result?.stdout ??
  ''
).trim();

if (!out) {
  json({ fire: false, state: trigger.state ?? {} });
} else {
  let next;
  try {
    next = JSON.parse(out);
  } catch (e) {
    // Almost always PRAYER_LAT / PRAYER_LON being unset, which prayer.sh reports
    // on stderr. Staying quiet is right: a misconfigured location must not
    // announce a wrong time, and must not spam the run log either.
    json({ fire: false, state: trigger.state ?? {} });
    next = null;
  }

  if (next && !next.error) {
    const already = trigger.state?.lastAnnounced;
    const fire = Boolean(next.due) && already !== next.id;
    json({
      fire,
      // Cron appends this to the agent-turn message. The prayer name is given in
      // Arabic so the model does not have to translate it, and the instruction
      // is explicit because a scheduled job infers its language from nothing.
      message: fire
        ? `حان الآن وقت صلاة ${next.name_ar} (${next.hhmm}). ` +
          `أعلن ذلك بجملة واحدة قصيرة بالعربية الفصحى، دون أي إضافات.`
        : undefined,
      // Only advance the marker when firing. Recording it on a quiet evaluation
      // would consume the id and silence the actual announcement a minute later.
      state: fire ? { lastAnnounced: next.id } : (trigger.state ?? {}),
    });
  }
}
