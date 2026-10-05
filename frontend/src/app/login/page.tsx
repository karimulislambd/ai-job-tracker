import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth-form";
import { Spinner } from "@/components/ui";

export const metadata: Metadata = { title: "Log in" };

export default function LoginPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <AuthForm mode="login" />
    </Suspense>
  );
}
