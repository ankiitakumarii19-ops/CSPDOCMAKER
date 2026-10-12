"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import BrandLogo from "../../components/BrandLogo";
import { api } from "../../lib/api";
import type { ApiError, SignInResult, WorkspaceChoice } from "../../lib/api";

/**
 * Authentication — the supplied design: navy branding panel on the left,
 * tabbed Login / Create Account on the right.
 *
 * The mockup's two buttons ("Login as RM" / "Login Admin") were demo
 * shortcuts that skipped authentication and chose a role by hand. The role
 * comes from the server here, so they are one Sign In button in the same
 * style; everything else follows the markup.
 */
export default function AuthPage() {
  const router = useRouter();

  const [authTab, setAuthTab] = useState<"login" | "register">("login");

  // The allowed sign-in domains come from the server, so this form and the
  // check behind it cannot drift apart. Until it answers, the form does not
  // pre-judge the address — the server still rejects a wrong domain.
  const [domains, setDomains] = useState<string[]>([]);
  const [domainsText, setDomainsText] = useState("your company");
  const [theme, setTheme] = useState<"light" | "dark">("light");

  // Login
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otpStep, setOtpStep] = useState(false);
  // Seconds until Resend becomes available again. The server allows only a
  // few codes a minute, so letting someone press this repeatedly would just
  // earn them a 429 — the countdown makes the wait visible instead.
  const [resendIn, setResendIn] = useState(0);
  const [resending, setResending] = useState(false);

  // Register
  const [registerStep, setRegisterStep] = useState(1);
  const [regEmail, setRegEmail] = useState("");
  const [regName, setRegName] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regRole, setRegRole] = useState("rm");
  // Only for a Super Admin creating their own workspace.
  const [regWorkspace, setRegWorkspace] = useState("");

  // Someone in more than one workspace chooses one at every login.
  const [choices, setChoices] = useState<WorkspaceChoice[] | null>(null);
  const [chosen, setChosen] = useState("");
  const [selectionToken, setSelectionToken] = useState("");

  // Password reset. The supplied design has a "Forgot password?" link but no
  // screen behind it; these two steps are that screen, in the same markup.
  const [resetStep, setResetStep] = useState<0 | 1 | 2>(0);
  const [resetEmail, setResetEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");

  // Shared
  const [digits, setDigits] = useState<string[]>(Array(6).fill(""));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .authConfig()
      .then((res) => {
        if (cancelled) return;
        setDomains(res.allowed_email_domains);
        setDomainsText(res.allowed_email_domains_text);
      })
      .catch(() => {
        /* Leave it open; the server is the authority either way. */
      })
      .finally(() => {
        // Sent here because the login ran out (api.ts): say so.
        if (!cancelled && new URLSearchParams(window.location.search).has("expired")) {
          setError("Your session has expired. Please sign in again.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const allowedDomain = (value: string) =>
    domains.length === 0 ||
    domains.some((d) => value.trim().toLowerCase().endsWith(`@${d}`));

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* private browsing */
    }
  };

  const otp = digits.join("");

  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = setTimeout(() => setResendIn((n) => n - 1), 1000);
    return () => clearTimeout(timer);
  }, [resendIn]);

  async function resend() {
    setResending(true);
    setError("");
    try {
      const res = await api.resendOtp(email);
      setInfo(res.message);
      setDigits(["", "", "", "", "", ""]);
      document.getElementById("otp-0")?.focus();
      setResendIn(30);
    } catch (e) {
      setError((e as ApiError).detail || "Could not send a new code.");
      // Even a refusal starts the clock: pressing again immediately would
      // only be refused again.
      setResendIn(30);
    } finally {
      setResending(false);
    }
  }

  const setDigit = (index: number, value: string) => {
    const clean = value.replace(/\D/g, "").slice(-1);
    const next = [...digits];
    next[index] = clean;
    setDigits(next);
    if (clean && index < 5) {
      document.getElementById(`otp-${index + 1}`)?.focus();
    }
  };

  const doLogin = async () => {
    setError("");
    setInfo("");
    if (!allowedDomain(email)) {
      setError(`Only ${domainsText} email addresses are allowed.`);
      return;
    }
    setLoading(true);
    try {
      await api.login({ email, password });
      setDigits(Array(6).fill(""));
      setOtpStep(true);
      setInfo("We have emailed you a code.");
    } catch (err) {
      setError((err as ApiError).detail || "Login failed.");
    } finally {
      setLoading(false);
    }
  };

  const doRegister = async () => {
    setError("");
    if (!allowedDomain(regEmail)) {
      setError(`Only ${domainsText} email addresses are allowed.`);
      return;
    }
    setLoading(true);
    try {
      await api.signup({
        email: regEmail,
        name: regName,
        password: regPassword,
        requested_role: regRole,
        ...(regRole === "super_admin" && regWorkspace.trim()
          ? { workspace_name: regWorkspace.trim() }
          : {}),
      });
      setEmail(regEmail);
      setDigits(Array(6).fill(""));
      setRegisterStep(2);
      setInfo("Email domain verified.");
    } catch (err) {
      setError((err as ApiError).detail || "Could not create the account.");
    } finally {
      setLoading(false);
    }
  };

  const startReset = () => {
    setError("");
    setInfo("");
    setResetEmail(email);
    setNewPassword("");
    setDigits(Array(6).fill(""));
    setResetStep(1);
  };

  const requestResetCode = async () => {
    setError("");
    setInfo("");
    if (!allowedDomain(resetEmail)) {
      setError(`Only ${domainsText} email addresses are allowed.`);
      return;
    }
    setLoading(true);
    try {
      const res = await api.forgotPassword(resetEmail);
      // Deliberately not "we found your account": the server answers the
      // same way either way, and the screen must not say more than it knows.
      setInfo(res.message);
      setDigits(Array(6).fill(""));
      setResetStep(2);
    } catch (err) {
      setError((err as ApiError).detail || "Could not start the reset.");
    } finally {
      setLoading(false);
    }
  };

  const submitReset = async () => {
    setError("");
    setLoading(true);
    try {
      await api.resetPassword({
        email: resetEmail,
        otp,
        new_password: newPassword,
      });
      setResetStep(0);
      setEmail(resetEmail);
      setPassword("");
      setInfo("Your password has been changed. You can now log in.");
    } catch (err) {
      setError((err as ApiError).detail || "Could not reset the password.");
    } finally {
      setLoading(false);
    }
  };

  const verify = async () => {
    setError("");
    setLoading(true);
    try {
      const res = await api.verifyOtp({ email, otp });
      if (res.verified && res.choose_workspace && res.workspaces) {
        setChoices(res.workspaces);
        setChosen(res.workspaces[0]?.id ?? "");
        setSelectionToken(res.selection_token ?? "");
        return;
      }
      if (!res.verified || !res.access_token) {
        setError("That code was not accepted.");
        return;
      }
      finishSignIn(res);
    } catch (err) {
      setError((err as ApiError).detail || "Verification failed.");
    } finally {
      setLoading(false);
    }
  };

  const enterWorkspace = async () => {
    setError("");
    setLoading(true);
    try {
      const res = await api.selectWorkspace({
        selection_token: selectionToken,
        workspace_id: chosen,
      });
      if (!res.access_token) {
        setError("Could not open that workspace.");
        return;
      }
      finishSignIn(res);
    } catch (err) {
      setError((err as ApiError).detail || "Could not open that workspace.");
      // An expired choice cannot be retried: start the login again.
      if ((err as ApiError).status === 401) {
        setChoices(null);
        setOtpStep(false);
      }
    } finally {
      setLoading(false);
    }
  };

  const finishSignIn = (res: SignInResult) => {
    api.setToken(res.access_token!);
    try {
      if (res.refresh_token) {
        sessionStorage.setItem("refresh_token", res.refresh_token);
      }
      sessionStorage.setItem(
        "user",
        JSON.stringify({
          email,
          role: res.role,
          name: res.name,
          workspace_id: res.workspace_id,
          workspace_name: res.workspace_name,
        })
      );
    } catch {
      /* private browsing */
    }
    router.replace(
      res.role === "admin" || res.role === "super_admin" ? "/admin" : "/rm"
    );
  };

  const otpBoxes = (
    <div className="flex gap-2">
      {digits.map((digit, index) => (
        <input
          key={index}
          id={`otp-${index}`}
          type="text"
          inputMode="numeric"
          maxLength={1}
          value={digit}
          onChange={(e) => setDigit(index, e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Backspace" && !digits[index] && index > 0) {
              document.getElementById(`otp-${index - 1}`)?.focus();
            }
          }}
          className="w-12 h-12 text-center text-xl font-bold rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 dark:text-white focus:ring-2 focus:ring-eko outline-none"
        />
      ))}
    </div>
  );

  return (
    <div className="relative flex h-full w-full">
      {/* Brand mark, top-left of the page. Above the navy panel's own
          z-10 content so it stays visible on wide screens. */}
      <div className="absolute top-6 left-6 z-20">
        <BrandLogo />
      </div>

      {/* Left: Branding Graphic (Hidden on mobile) */}
      <div className="hidden lg:flex w-1/2 bg-navy-900 relative items-center justify-center overflow-hidden">
        <div className="absolute inset-0 opacity-20">
          <svg className="h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
            <path d="M0,100 C30,60 70,60 100,0 L100,100 Z" fill="#00B259"></path>
          </svg>
        </div>
        <div className="relative z-10 text-center px-12">
          <div className="flex items-center justify-center gap-3 mb-6">
            <div className="w-12 h-12 bg-eko rounded-lg flex items-center justify-center text-white text-2xl font-bold">
              E
            </div>
            <h1 className="text-4xl font-bold text-white tracking-tight">CSPdocMaker</h1>
          </div>
          <p className="text-gray-300 text-lg max-w-md mx-auto">
            Financial Infrastructure for Bharat. Seamlessly manage and generate
            compliance documents for your Customer Service Points.
          </p>
        </div>
      </div>

      {/* Right: Auth Forms */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-8 bg-white dark:bg-gray-900">
        <div className="w-full max-w-md">
          {/* Theme Toggle in Auth */}
          <div className="absolute top-6 right-6">
            <button
              onClick={toggleTheme}
              className="p-2 rounded-full hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors text-gray-500 dark:text-gray-400"
            >
              <i className={`fas ${theme === "dark" ? "fa-sun" : "fa-moon"}`}></i>
            </button>
          </div>

          {/* Header */}
          <div className="text-center mb-8 lg:hidden">
            <div className="flex items-center justify-center gap-2 mb-2">
              <div className="w-8 h-8 bg-eko rounded border flex items-center justify-center text-white font-bold">
                E
              </div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                CSPdocMaker
              </h1>
            </div>
          </div>

          {/* Auth Tabs */}
          <div className="flex space-x-1 bg-gray-100 dark:bg-gray-800 p-1 rounded-xl mb-8">
            <button
              onClick={() => {
                setAuthTab("login");
                setError("");
                setOtpStep(false);
              }}
              className={`w-1/2 py-2.5 text-sm font-medium rounded-lg transition-all ${
                authTab === "login"
                  ? "bg-white dark:bg-gray-700 shadow-sm text-gray-900 dark:text-white"
                  : "text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              }`}
            >
              Login
            </button>
            <button
              onClick={() => {
                setAuthTab("register");
                setError("");
                setRegisterStep(1);
              }}
              className={`w-1/2 py-2.5 text-sm font-medium rounded-lg transition-all ${
                authTab === "register"
                  ? "bg-white dark:bg-gray-700 shadow-sm text-gray-900 dark:text-white"
                  : "text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              }`}
            >
              Create Account
            </button>
          </div>

          {error && (
            <div className="p-3 mb-4 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded-lg text-sm">
              <i className="fas fa-circle-exclamation mr-2"></i>
              {error}
            </div>
          )}

          {/* Choose a workspace — only for someone in more than one */}
          {choices && (
            <div>
              <h2 className="text-2xl font-bold mb-6 text-gray-900 dark:text-white">
                Choose a workspace
              </h2>
              <div className="space-y-3">
                {choices.map((w) => (
                  <label
                    key={w.id}
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                      chosen === w.id
                        ? "border-eko bg-eko-light dark:bg-eko/10"
                        : "border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800"
                    }`}
                  >
                    <input
                      type="radio"
                      name="workspace"
                      checked={chosen === w.id}
                      onChange={() => setChosen(w.id)}
                      className="accent-eko"
                    />
                    <span className="flex-1 text-gray-900 dark:text-white font-medium">
                      {w.name}
                    </span>
                    <span className="text-xs text-gray-500">
                      {w.role === "super_admin"
                        ? "Super Admin"
                        : w.role === "admin"
                        ? "Administrator"
                        : "RM"}
                    </span>
                  </label>
                ))}
                <div className="flex gap-3 mt-6">
                  <button
                    onClick={() => {
                      setChoices(null);
                      setOtpStep(false);
                      setRegisterStep(1);
                    }}
                    className="w-1/3 py-2.5 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 font-medium rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-all"
                  >
                    Back
                  </button>
                  <button
                    onClick={enterWorkspace}
                    disabled={loading || !chosen}
                    className="w-2/3 py-2.5 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white font-medium rounded-lg transition-all"
                  >
                    {loading ? "Opening..." : "Continue"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Login Form */}
          {!choices && authTab === "login" && !otpStep && resetStep === 0 && (
            <div>
              <h2 className="text-2xl font-bold mb-6 text-gray-900 dark:text-white">
                Welcome back
              </h2>
              {info && (
                <div className="p-3 bg-eko-light dark:bg-eko/10 text-eko-dark dark:text-eko rounded-lg text-sm mb-4">
                  <i className="fas fa-check-circle mr-2"></i> {info}
                </div>
              )}
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Email Address
                  </label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-eko focus:border-eko dark:text-white outline-none transition-all"
                    placeholder={`name@${domains[0] ?? "eko.co.in"}`}
                  />
                </div>
                <div>
                  <div className="flex justify-between items-center mb-1">
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                      Password
                    </label>
                    <button
                      type="button"
                      onClick={startReset}
                      className="text-xs text-eko font-medium hover:underline"
                    >
                      Forgot password?
                    </button>
                  </div>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && doLogin()}
                    className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-eko focus:border-eko dark:text-white outline-none transition-all"
                    placeholder="••••••••"
                  />
                </div>

                <div className="pt-2">
                  <button
                    onClick={doLogin}
                    disabled={loading}
                    className="w-full py-2.5 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white font-medium rounded-lg shadow-sm shadow-green-500/30 transition-all flex justify-center items-center gap-2"
                  >
                    <span>{loading ? "Signing in..." : "Login"}</span>
                    <i className="fas fa-arrow-right text-xs"></i>
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Forgot password — ask for the address */}
          {!choices && authTab === "login" && resetStep === 1 && (
            <div>
              <h2 className="text-2xl font-bold mb-6 text-gray-900 dark:text-white">
                Reset your password
              </h2>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Email Address
                  </label>
                  <input
                    type="email"
                    value={resetEmail}
                    onChange={(e) => setResetEmail(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && requestResetCode()}
                    className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-eko focus:border-eko dark:text-white outline-none transition-all"
                    placeholder={`name@${domains[0] ?? "eko.co.in"}`}
                  />
                </div>
                <div className="flex gap-3 mt-6">
                  <button
                    onClick={() => {
                      setResetStep(0);
                      setError("");
                      setInfo("");
                    }}
                    className="w-1/3 py-2.5 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 font-medium rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-all"
                  >
                    Back
                  </button>
                  <button
                    onClick={requestResetCode}
                    disabled={loading}
                    className="w-2/3 py-2.5 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white font-medium rounded-lg transition-all"
                  >
                    {loading ? "Sending..." : "Send reset code"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Forgot password — code and new password */}
          {!choices && authTab === "login" && resetStep === 2 && (
            <div>
              <h2 className="text-2xl font-bold mb-6 text-gray-900 dark:text-white">
                Choose a new password
              </h2>
              <div className="space-y-4">
                {info && (
                  <div className="p-3 bg-eko-light dark:bg-eko/10 text-eko-dark dark:text-eko rounded-lg text-sm mb-4">
                    <i className="fas fa-check-circle mr-2"></i> {info}
                  </div>
                )}
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Enter the code sent to your email
                  </label>
                  {otpBoxes}
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    New Password
                  </label>
                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-eko focus:border-eko dark:text-white outline-none transition-all"
                    placeholder="At least 8 characters"
                  />
                </div>
                <div className="flex gap-3 mt-6">
                  <button
                    onClick={() => {
                      setResetStep(1);
                      setError("");
                    }}
                    className="w-1/3 py-2.5 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 font-medium rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-all"
                  >
                    Back
                  </button>
                  <button
                    onClick={submitReset}
                    disabled={
                      loading || otp.length !== 6 || newPassword.length < 8
                    }
                    className="w-2/3 py-2.5 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white font-medium rounded-lg transition-all"
                  >
                    {loading ? "Saving..." : "Set new password"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Login — OTP */}
          {!choices && authTab === "login" && otpStep && resetStep === 0 && (
            <div>
              <h2 className="text-2xl font-bold mb-6 text-gray-900 dark:text-white">
                Verify it&apos;s you
              </h2>
              <div className="space-y-4">
                {info && (
                  <div className="p-3 bg-eko-light dark:bg-eko/10 text-eko-dark dark:text-eko rounded-lg text-sm mb-4">
                    <i className="fas fa-check-circle mr-2"></i> {info}
                  </div>
                )}
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Enter OTP sent to {email}
                  </label>
                  {otpBoxes}
                  <div className="flex justify-between items-center mt-3">
                    <span className="text-xs text-gray-500">
                      Didn&apos;t get it, or has it expired?
                    </span>
                    <button
                      type="button"
                      onClick={resend}
                      disabled={resending || resendIn > 0}
                      className="text-xs font-medium text-eko hover:underline disabled:text-gray-400 disabled:no-underline"
                    >
                      {resending
                        ? "Sending…"
                        : resendIn > 0
                        ? `Resend in ${resendIn}s`
                        : "Resend code"}
                    </button>
                  </div>
                </div>
                <div className="flex gap-3 mt-6">
                  <button
                    onClick={() => setOtpStep(false)}
                    className="w-1/3 py-2.5 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 font-medium rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-all"
                  >
                    Back
                  </button>
                  <button
                    onClick={verify}
                    disabled={loading || otp.length !== 6}
                    className="w-2/3 py-2.5 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white font-medium rounded-lg transition-all"
                  >
                    {loading ? "Verifying..." : "Verify & Login"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Register Form */}
          {!choices && authTab === "register" && (
            <div>
              <h2 className="text-2xl font-bold mb-6 text-gray-900 dark:text-white">
                Create an account
              </h2>

              {registerStep === 1 && (
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Full Name
                    </label>
                    <input
                      type="text"
                      value={regName}
                      onChange={(e) => setRegName(e.target.value)}
                      className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-eko outline-none dark:text-white"
                      placeholder="Your name"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Official Email
                    </label>
                    <input
                      type="email"
                      value={regEmail}
                      onChange={(e) => setRegEmail(e.target.value)}
                      className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-eko outline-none dark:text-white"
                      placeholder={`name@${domains[0] ?? "eko.co.in"}`}
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Password
                    </label>
                    <input
                      type="password"
                      value={regPassword}
                      onChange={(e) => setRegPassword(e.target.value)}
                      className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-eko outline-none dark:text-white"
                      placeholder="At least 8 characters"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Select Role
                    </label>
                    <select
                      value={regRole}
                      onChange={(e) => setRegRole(e.target.value)}
                      className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-eko outline-none dark:text-white"
                    >
                      <option value="rm">Relationship Manager (RM)</option>
                      <option value="admin">Administrator</option>
                      <option value="super_admin">
                        Workspace Owner (Super Admin)
                      </option>
                    </select>
                  </div>
                  {regRole === "super_admin" && (
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Workspace name
                      </label>
                      <input
                        type="text"
                        value={regWorkspace}
                        onChange={(e) => setRegWorkspace(e.target.value)}
                        maxLength={100}
                        className="w-full px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-eko outline-none dark:text-white"
                        placeholder="e.g. Patna Pilot"
                      />
                      <p className="text-xs text-gray-500 mt-1">
                        A new, empty workspace is created for you. Leave this
                        blank only if you are listed as a Super Admin of Eko
                        SBI Kiosk CSP.
                      </p>
                    </div>
                  )}
                  <button
                    onClick={doRegister}
                    disabled={loading}
                    className="w-full mt-4 py-2.5 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white font-medium rounded-lg transition-all"
                  >
                    {loading ? "Creating..." : "Continue to OTP"}
                  </button>
                </div>
              )}

              {registerStep === 2 && (
                <div className="space-y-4">
                  <div className="p-3 bg-eko-light dark:bg-eko/10 text-eko-dark dark:text-eko rounded-lg text-sm mb-4">
                    <i className="fas fa-check-circle mr-2"></i> Email domain verified.
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Enter OTP sent to email
                    </label>
                    {otpBoxes}
                  </div>
                  <div className="flex gap-3 mt-6">
                    <button
                      onClick={() => setRegisterStep(1)}
                      className="w-1/3 py-2.5 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 font-medium rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-all"
                    >
                      Back
                    </button>
                    <button
                      onClick={verify}
                      disabled={loading || otp.length !== 6}
                      className="w-2/3 py-2.5 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white font-medium rounded-lg transition-all"
                    >
                      {loading ? "Verifying..." : "Verify & Login"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
