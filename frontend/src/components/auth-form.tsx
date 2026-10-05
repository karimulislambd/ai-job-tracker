"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

import { DemoButton } from "./demo-button";
import { Logo } from "./logo";
import { Button, Card, Field, Input } from "./ui";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { login, register, status } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(
    params.get("expired") ? "Your session expired. Please log in again." : null,
  );
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (status === "authenticated") router.replace("/board");
  }, [status, router]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");
    setSubmitting(true);
    setError(null);
    setFieldErrors({});
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, String(form.get("full_name") ?? ""));
      router.replace("/board");
    } catch (err) {
      if (err instanceof ApiError && err.code === "validation_error" && Array.isArray(err.details)) {
        const map: Record<string, string> = {};
        for (const d of err.details as { loc: string[]; msg: string }[]) {
          map[String(d.loc.at(-1))] = d.msg.replace(/^Value error, /, "");
        }
        setFieldErrors(map);
      } else {
        setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  const isLogin = mode === "login";
  return (
    <div className="flex min-h-full flex-1 flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>
        <Card className="p-6">
          <h1 className="text-xl font-semibold">{isLogin ? "Welcome back" : "Create your account"}</h1>
          <p className="mt-1 text-sm text-fg-muted">
            {isLogin ? "Log in to your job search." : "Start tracking applications in seconds."}
          </p>
          <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4" noValidate>
            {!isLogin && (
              <Field label="Name (optional)" htmlFor="full_name" error={fieldErrors.full_name}>
                <Input id="full_name" name="full_name" autoComplete="name" maxLength={120} />
              </Field>
            )}
            <Field label="Email" htmlFor="email" error={fieldErrors.email}>
              <Input id="email" name="email" type="email" autoComplete="email" required />
            </Field>
            <Field
              label="Password"
              htmlFor="password"
              error={fieldErrors.password}
              hint={isLogin ? undefined : "At least 8 characters, mixing letters with digits or symbols."}
            >
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete={isLogin ? "current-password" : "new-password"}
                required
                minLength={isLogin ? 1 : 8}
              />
            </Field>
            {error && (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
            <Button type="submit" loading={submitting} className="w-full">
              {isLogin ? "Log in" : "Create account"}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-fg-muted">
            {isLogin ? "New here? " : "Already have an account? "}
            <Link className="font-medium text-accent hover:underline" href={isLogin ? "/register" : "/login"}>
              {isLogin ? "Create an account" : "Log in"}
            </Link>
          </p>
        </Card>
        <div className="mt-6 flex flex-col items-center gap-2">
          <span className="text-xs uppercase tracking-wider text-fg-subtle">or</span>
          <DemoButton size="md" label="Explore the demo instead" />
        </div>
      </div>
    </div>
  );
}
