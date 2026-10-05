import { BriefcaseBusiness } from "lucide-react";
import Link from "next/link";

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2 font-semibold tracking-tight">
      <span className="flex size-8 items-center justify-center rounded-lg bg-accent text-accent-fg">
        <BriefcaseBusiness className="size-4" aria-hidden />
      </span>
      <span>AI Job Tracker</span>
    </Link>
  );
}
