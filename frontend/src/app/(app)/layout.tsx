"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppShell } from "@/components/app-shell";
import { Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [status, router]);

  if (status !== "authenticated") return <Spinner label="Loading your workspace" />;
  return <AppShell>{children}</AppShell>;
}
