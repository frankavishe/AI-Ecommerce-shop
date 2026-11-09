/**
 * Django returns absolute media URLs built from whatever host it saw (e.g. http://api:8000/media/x.jpg).
 * The browser reaches media through this site's /media rewrite, so keep only the path.
 */
export function mediaPath(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const { pathname } = new URL(url, "http://local");
    return pathname.startsWith("/media/") ? pathname : null;
  } catch {
    return null;
  }
}
