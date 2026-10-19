/** Choosing a place to search near: cities with trial sites, from the sites' own records. */
import { useQuery } from "@tanstack/react-query";
import { ChevronsUpDown, MapPin, X } from "lucide-react";
import { useState } from "react";
import { placesQuery } from "@/api/advanced";
import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatNumber } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";

export type Place = Schemas["PlaceOut"];

/** A place as it reads: city, state, country. */
export function placeName(place: Place): string {
  const parts = [place.city, place.state, place.country_name ?? place.country];
  return [...new Set(parts.filter((part): part is string => !!part))].join(", ");
}

export function PlacePicker({
  place,
  onChoose,
}: {
  place: string | undefined;
  onChoose: (place: Place | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const typed = useDebounced(q, 150);
  const found = useQuery({ ...placesQuery(typed), enabled: open && typed.trim().length > 0 });
  const places = typed.trim() ? (found.data?.places ?? []) : [];

  return (
    <div className="flex min-w-0 gap-1.5">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            aria-label="Place"
            className="h-8 min-w-0 flex-1 justify-between font-normal"
          >
            <span className="flex min-w-0 items-center gap-2">
              <MapPin className="text-muted-foreground" />
              {place ? (
                <span className="truncate">{place}</span>
              ) : (
                <span className="text-muted-foreground">Any place</span>
              )}
            </span>
            <ChevronsUpDown className="text-muted-foreground" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-(--radix-popover-trigger-width) min-w-72 p-0" align="start">
          <Command shouldFilter={false}>
            <CommandInput
              placeholder="A city: Toronto, Cambridge, us…"
              value={q}
              onValueChange={setQ}
            />
            <CommandList>
              <CommandEmpty>
                {!typed.trim()
                  ? "Type a city's name. After a comma, its state or country narrows it."
                  : found.isFetching
                    ? "Looking…"
                    : `No trial sites in a place called “${typed}”.`}
              </CommandEmpty>
              {places.length > 0 && (
                <CommandGroup heading="Places with trial sites">
                  {places.map((option) => (
                    <CommandItem
                      key={`${option.lat},${option.lon}`}
                      value={`${option.lat},${option.lon}`}
                      onSelect={() => {
                        onChoose(option);
                        setOpen(false);
                      }}
                      className="flex items-center gap-3"
                    >
                      <span className="min-w-0 flex-1 truncate">{placeName(option)}</span>
                      <span className="text-xs text-muted-foreground tabular">
                        {formatNumber(option.sites)} sites
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {place && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label="Any place"
          onClick={() => onChoose(null)}
        >
          <X />
        </Button>
      )}
    </div>
  );
}
