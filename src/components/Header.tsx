import type { FC } from 'react';
import { Bus as BusIcon, Radio, ShieldCheck } from 'lucide-react';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';

interface HeaderProps {
  onOpenPrivacy: () => void;
  onOpenShareLocation?: () => void;
  isSharingActive?: boolean;
}

export const Header: FC<HeaderProps> = ({
  onOpenPrivacy,
  onOpenShareLocation,
  isSharingActive = false,
}) => {
  return (
    <header className="bg-white border-b border-gray-200 sticky top-0 z-30 shadow-xs">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Brand */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-blue-600 flex items-center justify-center text-white shadow-sm">
              <BusIcon className="w-5 h-5" />
            </div>
            <div>
              <div className="text-base font-bold text-gray-900 tracking-tight flex items-center gap-2">
                <span>Belagavi Central Division Radar</span>
                <span className="hidden md:inline-flex items-center text-[10px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.2 rounded">
                  100% Frictionless
                </span>
              </div>
              <div className="text-xs text-gray-500">
                North Western Karnataka RTC • Public Live Transit Radar (Open Access)
              </div>
            </div>
          </div>

          {/* Right actions: Live status indicators & crowdsource sharing button */}
          <div className="flex items-center gap-2.5">
            <div className="hidden md:flex items-center gap-2">
              <Badge variant="success" dot>
                Live GPS Active
              </Badge>
              <Badge variant="blue">
                Belagavi Division
              </Badge>
              <Badge variant="gray">
                No Login Required
              </Badge>
            </div>

            {onOpenShareLocation && (
              <Button
                variant={isSharingActive ? 'primary' : 'secondary'}
                size="sm"
                leftIcon={<Radio className={`w-4 h-4 ${isSharingActive ? 'animate-pulse text-white' : 'text-blue-600'}`} />}
                onClick={onOpenShareLocation}
                className={isSharingActive ? 'bg-emerald-600 hover:bg-emerald-700 text-white' : ''}
              >
                {isSharingActive ? 'Broadcasting GPS' : 'Share Live Bus Location'}
              </Button>
            )}

            <Button
              variant="secondary"
              size="sm"
              leftIcon={<ShieldCheck className="w-4 h-4 text-gray-500" />}
              onClick={onOpenPrivacy}
              className="hidden sm:inline-flex"
            >
              Privacy & Notice
            </Button>
          </div>
        </div>
      </div>
    </header>
  );
};

export default Header;
