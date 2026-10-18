import { Link } from "@tanstack/react-router";
import { SearchIcon } from "lucide-react";
import { useMemo, useState } from "react";
import type { TrialDetail } from "@/api/client";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { countryName, flag, formatNumber } from "@/lib/format";
import { Panel } from "./sections";

const PAGE = 50;

export function LocationsTab({ trial }: { trial: TrialDetail }) {
  const [search, setSearch] = useState("");
  const [country, setCountry] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE);

  const byCountry = useMemo(() => {
    const counts = new Map<string, number>();
    for (const location of trial.locations) {
      const code = location.country_code ?? "";
      counts.set(code, (counts.get(code) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [trial.locations]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return trial.locations.filter(
      (location) =>
        (country === null || (location.country_code ?? "") === country) &&
        (!needle ||
          [location.facility, location.city, location.state, countryName(location.country_code)]
            .join(" ")
            .toLowerCase()
            .includes(needle)),
    );
  }, [trial.locations, search, country]);

  if (trial.locations.length === 0) {
    return (
      <Panel title="Locations">
        <p className="text-sm text-muted-foreground">This trial lists no sites.</p>
      </Panel>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title={`${formatNumber(trial.locations.length)} sites in ${byCountry.length} ${byCountry.length === 1 ? "country" : "countries"}`}
      >
        <div className="flex flex-wrap gap-1.5">
          {byCountry.map(([code, count]) => (
            <button
              key={code}
              type="button"
              aria-pressed={country === code}
              onClick={() => setCountry(country === code ? null : code)}
              className="inline-flex h-7 items-center gap-1.5 rounded-full border bg-muted/30 px-2.5 text-xs transition-colors hover:bg-muted aria-pressed:border-foreground/30 aria-pressed:bg-foreground aria-pressed:text-background"
            >
              <span>{flag(code)}</span>
              {countryName(code || null)}
              <span className="tabular opacity-70">{formatNumber(count)}</span>
            </button>
          ))}
        </div>
        {byCountry.length > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">
            Find other trials in{" "}
            {byCountry
              .map(([code]) => code)
              .filter(Boolean)
              .slice(0, 3)
              .map((code, index) => (
                <span key={code}>
                  {index > 0 && ", "}
                  <Link
                    to="/trials"
                    search={{ countries: [code] }}
                    className="underline-offset-2 hover:text-foreground hover:underline"
                  >
                    {countryName(code)}
                  </Link>
                </span>
              ))}
            .
          </p>
        )}
      </Panel>
      <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
        <div className="flex items-center gap-2 border-b p-3">
          <div className="relative w-full max-w-xs">
            <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setShown(PAGE);
              }}
              placeholder="Find a site or city…"
              aria-label="Find a site"
              className="h-8 pl-8 text-sm"
            />
          </div>
          <span className="ml-auto text-xs text-muted-foreground tabular">
            {formatNumber(rows.length)} shown
          </span>
        </div>
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="pl-4">Site</TableHead>
              <TableHead className="hidden sm:table-cell">City</TableHead>
              <TableHead>Country</TableHead>
              <TableHead className="hidden md:table-cell">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.slice(0, shown).map((location, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: locations have only their position
              <TableRow key={index}>
                <TableCell className="pl-4 whitespace-normal">
                  <div className="font-medium">{location.facility ?? "—"}</div>
                  <div className="text-xs text-muted-foreground sm:hidden">
                    {[location.city, location.state].filter(Boolean).join(", ")}
                  </div>
                </TableCell>
                <TableCell className="hidden whitespace-normal text-muted-foreground sm:table-cell">
                  {[location.city, location.state].filter(Boolean).join(", ") || "—"}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <span className="inline-flex items-center gap-1.5">
                    <span aria-hidden="true">{flag(location.country_code)}</span>
                    {countryName(location.country_code)}
                  </span>
                </TableCell>
                <TableCell className="hidden md:table-cell">
                  {location.status ? (
                    <StatusBadge status={location.status} />
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {rows.length > shown && (
          <div className="border-t p-3 text-center">
            <Button variant="outline" size="sm" onClick={() => setShown(shown + 200)}>
              Show more ({formatNumber(rows.length - shown)} left)
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
