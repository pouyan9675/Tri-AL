import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/lib/theme";

/** Light ↔ dark. "System" is in Settings and the ⌘K palette. */
export function ThemeToggle() {
  const { resolved, setTheme } = useTheme();
  const next = resolved === "dark" ? "light" : "dark";
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={`Switch to the ${next} theme`}
      title={`Switch to the ${next} theme`}
      onClick={() => setTheme(next)}
    >
      <Sun className="scale-100 rotate-0 transition-all dark:scale-0 dark:-rotate-90" />
      <Moon className="absolute scale-0 rotate-90 transition-all dark:scale-100 dark:rotate-0" />
    </Button>
  );
}
