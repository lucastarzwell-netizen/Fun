/** Search schedules: a cron string plus how often it repeats (see backend models.SearchProfile). */

export type Every = "week" | "2weeks" | "month";

/** day: 0-6 = Sunday-Saturday (7 = every day, weekly only) or 1-31 for monthly. */
export interface Schedule {
  every: Every;
  day: number;
  time: string; // "HH:MM"
}

export const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const hm = (time: string) => time.split(":").map(Number);
const pad = (n: string) => n.padStart(2, "0");

export function parseSchedule(cron: string, every: Every = "week"): Schedule | null {
  const c = cron.trim();
  if (every === "month") {
    const m = c.match(/^(\d{1,2}) (\d{1,2}) (\d{1,2}) \* \*$/);
    return m ? { every, day: Number(m[3]), time: `${pad(m[2])}:${pad(m[1])}` } : null;
  }
  const m = c.match(/^(\d{1,2}) (\d{1,2}) \* \* ([0-6]|\*)$/);
  if (!m || (every === "2weeks" && m[3] === "*")) return null;
  return { every, day: m[3] === "*" ? 7 : Number(m[3]), time: `${pad(m[2])}:${pad(m[1])}` };
}

export function toCron(s: Schedule): string {
  const [h, m] = hm(s.time);
  if (s.every === "month") return `${m} ${h} ${s.day} * *`;
  return `${m} ${h} * * ${s.every === "week" && s.day === 7 ? "*" : s.day}`;
}

/** Switch frequency, keeping the time and picking a sensible day. */
export function withEvery(s: Schedule, every: Every): Schedule {
  if (every === s.every) return s;
  if (every === "month") return { every, day: 1, time: s.time };
  const day = s.every === "month" || s.day === 7 ? 5 : s.day; // Friday
  return { every, day, time: s.time };
}

const ordinal = (n: number) =>
  `${n}${n % 10 === 1 && n !== 11 ? "st" : n % 10 === 2 && n !== 12 ? "nd" : n % 10 === 3 && n !== 13 ? "rd" : "th"}`;

export function describeSchedule(s: Schedule): string {
  if (s.every === "month")
    return `Monthly on the ${ordinal(s.day)}${s.day > 28 ? " (or the month's last day)" : ""} at ${s.time}`;
  if (s.every === "2weeks") return `Every other ${WEEKDAYS[s.day]} at ${s.time}`;
  return s.day === 7 ? `Every day at ${s.time}` : `Every ${WEEKDAYS[s.day]} at ${s.time}`;
}

export const MONTH_DAYS = Array.from({ length: 31 }, (_, i) => i + 1);
export { ordinal };
