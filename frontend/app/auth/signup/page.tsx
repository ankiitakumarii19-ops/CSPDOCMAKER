"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Signing up lives on the auth screen's "Create Account" tab, so this is
 *  kept only so an old link does not 404. */
export default function SignupRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/auth/login");
  }, [router]);

  return (
    <div className="flex h-screen w-full items-center justify-center bg-gray-50 dark:bg-navy-900">
      <div className="w-12 h-12 border-4 border-gray-200 border-t-eko rounded-full animate-spin" />
    </div>
  );
}
