"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useSessionUser } from "./lib/useSessionUser";

/** Entry point. Signed-in users go to their dashboard; everyone else to the
 *  auth screen, which is where the design starts. */
export default function HomePage() {
  const router = useRouter();
  const user = useSessionUser();

  useEffect(() => {
    if (user === undefined) return;
    router.replace(
      user === null ? "/auth/login" : user.role === "admin" ? "/admin" : "/rm"
    );
  }, [user, router]);

  return (
    <div className="flex h-screen w-full items-center justify-center bg-gray-50 dark:bg-navy-900">
      <div className="w-12 h-12 border-4 border-gray-200 border-t-eko rounded-full animate-spin" />
    </div>
  );
}
