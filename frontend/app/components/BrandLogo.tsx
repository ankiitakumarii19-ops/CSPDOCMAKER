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
}: {
  className?: string;
  height?: number;
}) {
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
