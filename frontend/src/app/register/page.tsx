import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth-form";
import { Spinner } from "@/components/ui";

export const metadata: Metadata = { title: "Sign up" };

export default function RegisterPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <AuthForm mode="register" />
    </Suspense>
  );
}
