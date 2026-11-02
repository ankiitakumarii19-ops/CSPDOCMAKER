"use client";

/**
 * A bar across every screen of a TEST COPY of the app (No. 173), so nobody
 * mistakes it for the live one. The server says whether it is one
 * (TEST_COPY, /api/auth/config); on the live app nothing is shown.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";

export default function TestCopyBanner() {
  const [test, setTest] = useState(false);

  useEffect(() => {
    api
      .authConfig()
      .then((r) => setTest(!!r.test_copy))
      .catch(() => setTest(false));
  }, []);

  if (!test) return null;
  return (
    <div className="fixed top-0 inset-x-0 z-[100] bg-amber-400 text-amber-950 text-center text-xs font-bold py-0.5 pointer-events-none">
      TEST COPY — nothing here is sent to CSPs, and its data is not the live data
    </div>
  );
}
