/**
 * One way of matching a search (No. 175), for lists the screen filters
 * itself — the same rules as the server's (backend services/search_match.py):
 * part of a word is enough, capitals and extra spaces do not matter, and a
 * phone number is matched on its digits ("98123 45" finds +91-98123-45670).
 */

export function normalize(text: string | null | undefined): string {
  return (text ?? "").split(/\s+/).filter(Boolean).join(" ").toLowerCase();
}

/** Whether `query` is found in any of `texts`, or (3+ digits) in a phone. */
export function matches(
  query: string,
  texts: Array<string | null | undefined>,
  phones: Array<string | null | undefined> = []
): boolean {
  const term = normalize(query);
  if (!term) return true;
  if (texts.some((t) => normalize(t).includes(term))) return true;
  const digits = term.replace(/\D/g, "");
  return digits.length >= 3 && phones.some((p) => (p ?? "").replace(/\D/g, "").includes(digits));
}
