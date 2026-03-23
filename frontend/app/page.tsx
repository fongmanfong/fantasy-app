"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useLeague } from "@/hooks/useLeague";
import { api } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const { leagues, isLoading } = useLeague();

  useEffect(() => {
    if (isLoading) return;
    const check = async () => {
      try {
        const status = await api.auth.getStatus();
        if (!status.has_credentials || !status.is_authenticated) {
          router.replace("/setup");
        } else if (leagues.length === 0) {
          router.replace("/setup");
        } else {
          router.replace("/dashboard");
        }
      } catch {
        router.replace("/setup");
      }
    };
    check();
  }, [isLoading, leagues, router]);

  return null;
}
