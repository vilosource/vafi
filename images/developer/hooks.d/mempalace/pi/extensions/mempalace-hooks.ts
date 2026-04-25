import { execSync } from "node:child_process";

export default (pi: any) => {
  // Equivalent to Claude's Stop hook — fires on session exit
  pi.on("session_shutdown", async () => {
    try {
      execSync("mempalace hook run --hook stop --harness pi", {
        timeout: 10000,
        stdio: "ignore",
      });
    } catch {
      // Don't block shutdown if mempalace fails
    }
  });

  // Equivalent to Claude's PreCompact hook — fires before context compression
  pi.on("session_before_compact", async () => {
    try {
      execSync("mempalace hook run --hook precompact --harness pi", {
        timeout: 10000,
        stdio: "ignore",
      });
    } catch {
      // Don't block compaction if mempalace fails
    }
  });
};
