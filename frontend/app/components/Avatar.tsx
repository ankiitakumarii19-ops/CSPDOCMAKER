"use client";

/**
 * A person's profile picture, or their initials when they have none
 * (No. 171). Used wherever a signed-in person's name is shown: the admin
 * and RM headers, the Access list, the Replies screen.
 *
 * The picture needs the sign-in token, so it is fetched as a blob (a plain
 * <img src> cannot send it) and kept for the page's life; uploading or
 * removing one tells every Avatar on the page to look again.
 */

import { useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import type { ApiError } from "../lib/api";

const CHANGED = "profile-photo-changed";
const cache = new Map<string, Promise<string | null>>();

function load(email: string): Promise<string | null> {
  const key = email.toLowerCase();
  let hit = cache.get(key);
  if (!hit) {
    hit = api
      .profilePhoto(key)
      .then((blob) => (blob ? URL.createObjectURL(blob) : null))
      // A failure shows initials; it is not worth an error on every list row.
      .catch(() => null);
    cache.set(key, hit);
  }
  return hit;
}

function changed(email: string) {
  const key = email.toLowerCase();
  cache.get(key)?.then((url) => url && URL.revokeObjectURL(url));
  cache.delete(key);
  window.dispatchEvent(new CustomEvent(CHANGED, { detail: key }));
}

export function initialsOf(name: string): string {
  return (name || "?")
    .split(/\s+/)
    .filter(Boolean)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export default function Avatar({
  email,
  name,
  className = "w-8 h-8 text-sm bg-blue-600",
  initials,
}: {
  email: string;
  name: string;
  /** Size, text size and the initials' background. */
  className?: string;
  initials?: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const onChange = (e: Event) => {
      if ((e as CustomEvent<string>).detail === email.toLowerCase()) setVersion((v) => v + 1);
    };
    window.addEventListener(CHANGED, onChange);
    return () => window.removeEventListener(CHANGED, onChange);
  }, [email]);

  useEffect(() => {
    let current = true;
    if (email) load(email).then((u) => current && setUrl(u));
    return () => {
      current = false;
    };
  }, [email, version]);

  const base = `rounded-full shrink-0 overflow-hidden ${className}`;
  if (url) {
    // eslint-disable-next-line @next/next/no-img-element -- a blob URL, not an optimisable asset
    return <img src={url} alt={name} className={`${base} object-cover`} />;
  }
  return (
    <div className={`${base} text-white flex items-center justify-center font-bold`}>
      {initials ?? initialsOf(name)}
    </div>
  );
}

/**
 * Upload / change / remove one's own picture, for the header menus. The
 * file box lives outside the menu (`input`), so closing the menu does not
 * take it away while the file chooser is open.
 */
export function useProfilePhoto(email: string) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [has, setHas] = useState(false);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let current = true;
    if (email) load(email).then((u) => current && setHas(!!u));
    return () => {
      current = false;
    };
  }, [email, version]);

  const upload = async (file: File) => {
    setError("");
    try {
      await api.setProfilePhoto(file);
      changed(email);
      setVersion((v) => v + 1);
    } catch (e) {
      setError((e as ApiError).detail || "The picture could not be saved.");
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const remove = async () => {
    setError("");
    try {
      await api.removeProfilePhoto();
      changed(email);
      setVersion((v) => v + 1);
    } catch (e) {
      setError((e as ApiError).detail || "The picture could not be removed.");
    }
  };

  const input = (
    <input
      ref={fileRef}
      type="file"
      accept="image/jpeg,image/png,image/webp"
      className="hidden"
      onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
    />
  );

  return { has, error, input, pick: () => fileRef.current?.click(), remove, clearError: () => setError("") };
}

/** The menu lines: Add / Change / Remove picture. */
export function ProfilePhotoMenuItems({
  photo,
}: {
  photo: ReturnType<typeof useProfilePhoto>;
}) {
  const item =
    "w-full text-left px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors";
  return (
    <>
      <button onClick={photo.pick} className={item}>
        <i className="fas fa-camera mr-2"></i>
        {photo.has ? "Change picture" : "Add profile picture"}
      </button>
      {photo.has && (
        <button onClick={photo.remove} className={item}>
          <i className="fas fa-user-slash mr-2"></i> Remove picture
        </button>
      )}
      <div className="my-1 border-t border-gray-100 dark:border-gray-700"></div>
    </>
  );
}
