import Image from "next/image";

import { withBase } from "../lib/basePath";

/**
 * The eko KIOSK logo, top-left on every page.
 *
 * The supplied artwork has its own opaque background baked in (#00668F) and
 * white "KIOSK" lettering, so it is shown as a block rather than laid over a
 * page colour — on a white header the lettering would otherwise vanish.
 *
 * The source is 139x78, so the default 40px height renders at roughly 2x and
 * stays sharp on high-density screens. Sizes above that will soften.
 */
export default function BrandLogo({
  className = "",
  height = 40,
  logo = null,
  name = "",
}: {
  className?: string;
  height?: number;
  /** No. 240 (Stage 3): the organisation's own logo version, from
   *  /api/me/access (look.logo). None = the app's own, as before. */
  logo?: string | null;
  name?: string;
}) {
  if (logo) {
    // Same site, so the sign-in cookie goes with it; ?v= changes with the file.
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={withBase(`/api/me/logo?v=${encodeURIComponent(logo)}`)}
        alt={name ? `${name} logo` : "Logo"}
        style={{ height, width: "auto", maxWidth: height * 4 }}
        className={`object-contain ${className}`}
      />
    );
  }
  const width = Math.round((139 / 78) * height);
  return (
    <Image
      src={withBase("/brand/eko-kiosk.png")}
      alt="eko KIOSK"
      width={width}
      height={height}
      priority
      className={`rounded ${className}`}
    />
  );
}
