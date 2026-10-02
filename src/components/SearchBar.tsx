import type { FC, FormEvent } from 'react';
import { Search, MapPin, ArrowRight, RotateCcw } from 'lucide-react';
import { Button } from './ui/Button';
import type { Station } from '../types/database';

interface SearchBarProps {
  source: string;
  destination: string;
  stations: Station[];
  isLoading?: boolean;
  onSourceChange: (val: string) => void;
  onDestinationChange: (val: string) => void;
  onSearch: () => void;
  onReset: () => void;
}

export const SearchBar: FC<SearchBarProps> = ({
  source,
  destination,
  stations,
  isLoading = false,
  onSourceChange,
  onDestinationChange,
  onSearch,
  onReset,
}) => {
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSearch();
  };

  // Distinct station names derived dynamically from the backend stations list
  const uniqueStationNames = Array.from(
    new Set(stations.map((s) => s.name))
  );

  // Prominent division hubs to display as quick-select pills
  const quickHubs = [
    'BELAGAVI CBT', 'CHIKKODI', 'ATHANI', 'NIPPANI', 'SANKESHWAR',
    'RAIBAG', 'GOKAK', 'MIRAJ', 'SANGLI', 'VIJAYAPURA', 'JAMAKHANDI'
  ];

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-3.5 shadow-sm">
      {/* HTML Datalist providing native autocomplete from real backend stations */}
      <datalist id="stations-autocomplete">
        {uniqueStationNames.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>

      <form onSubmit={handleSubmit} className="space-y-2.5">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-2.5 items-center">
          {/* Origin Station */}
          <div className="md:col-span-5 relative">
            <div className="relative">
              <MapPin className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                list="stations-autocomplete"
                value={source}
                onChange={(e) => onSourceChange(e.target.value)}
                placeholder="Origin Station (e.g. BELAGAVI CBT)"
                className="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none text-gray-900 placeholder-gray-400 bg-white"
              />
            </div>
          </div>

          {/* Direction indicator */}
          <div className="hidden md:flex md:col-span-1 justify-center">
            <div className="w-7 h-7 rounded-full bg-gray-100 flex items-center justify-center text-gray-400">
              <ArrowRight className="w-3.5 h-3.5" />
            </div>
          </div>

          {/* Destination Station */}
          <div className="md:col-span-4 relative">
            <div className="relative">
              <MapPin className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                list="stations-autocomplete"
                value={destination}
                onChange={(e) => onDestinationChange(e.target.value)}
                placeholder="Destination Station (e.g. CHIKKODI, SHIRGUPPI)"
                className="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none text-gray-900 placeholder-gray-400 bg-white"
              />
            </div>
          </div>

          {/* Search & Reset Buttons */}
          <div className="md:col-span-2 flex items-center gap-1.5">
            <Button
              type="submit"
              variant="primary"
              size="sm"
              isLoading={isLoading}
              className="w-full py-2"
              leftIcon={<Search className="w-3.5 h-3.5" />}
            >
              Search
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={onReset}
              className="py-2 px-2.5"
              title="Reset"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>

        {/* Quick select hubs derived dynamically from backend stations */}
        {uniqueStationNames.length > 0 && (
          <div className="flex flex-wrap items-center gap-1 text-[11px] text-gray-500 pt-0.5">
            <span className="font-semibold text-gray-600 mr-1">Hubs:</span>
            {quickHubs.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => {
                  if (!source) {
                    onSourceChange(name);
                  } else {
                    onDestinationChange(name);
                  }
                }}
                className="px-1.5 py-0.5 bg-gray-100 hover:bg-gray-200 hover:text-blue-700 text-gray-700 rounded transition cursor-pointer"
              >
                {name}
              </button>
            ))}
          </div>
        )}
      </form>
    </div>
  );
};

export default SearchBar;
