"use client";

import { Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

import { Button, type ButtonProps } from "./ui";

/** One click → a private, pre-filled demo account (cloned server-side, deleted after 24h). */
export function DemoButton({ size = "lg", className, label = "Try the demo" }: {
  size?: ButtonProps["size"];
  className?: string;
  label?: string;
}) {
  const { startDemo } = useAuth();
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [slow, setSlow] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading) return;
    // Free-tier backends sleep when idle; tell the visitor why the first request is slow.
    const timer = setTimeout(() => setSlow(true), 3500);
    return () => clearTimeout(timer);
  }, [loading]);

  return (
    <div className="flex flex-col items-center gap-2">
      <Button
        size={size}
        className={className}
        loading={loading}
        onClick={async () => {
          setLoading(true);
          setSlow(false);
          setError(null);
          try {
            await startDemo();
            router.push("/board");
          } catch (e) {
            setError(e instanceof ApiError ? e.message : "Could not reach the server. Please try again.");
            setLoading(false);
          }
        }}
      >
        {!loading && <Sparkles className="size-4" aria-hidden />}
        {loading ? "Preparing your demo…" : label}
      </Button>
      <p className="min-h-5 text-xs text-fg-subtle" aria-live="polite">
        {error ? (
          <span className="text-danger">{error}</span>
        ) : slow ? (
          "Waking up the server (free tier) — this can take up to a minute the first time."
        ) : (
          "No sign-up. Your own private copy with sample data."
        )}
      </p>
    </div>
  );
}
