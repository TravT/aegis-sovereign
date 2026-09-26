import React from 'react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { FileText, ChevronRight } from 'lucide-react';

export interface CitationPillProps {
  index: number;
  title: string;
  heading?: string;
  confidence?: number;
  page?: number;
  active?: boolean;
  onClick?: () => void;
  className?: string;
}

export const CitationPill: React.FC<CitationPillProps> = ({
  index,
  title,
  heading,
  confidence,
  page,
  active = false,
  onClick,
  className,
}) => {
  const confidencePct = confidence ? Math.round(confidence * 100) : null;

  return (
    <button
      type="button"
      onClick={onClick}
      className={twMerge(
        clsx(
          'inline-flex items-center gap-2 px-3 py-1.5 rounded-md font-mono text-xs transition-all duration-200 border select-none group',
          active
            ? 'bg-[#D4AF37]/25 border-[#D4AF37] text-[#F3E5AB] shadow-[0_0_16px_rgba(212,175,55,0.35)] translate-y-[-1px]'
            : 'bg-[#141A24]/90 border-[#232B38] text-[#E6EDF3] hover:border-[#D4AF37]/60 hover:bg-[#1A2230] hover:text-[#F3E5AB]',
          className
        )
      )}
    >
      <FileText className={clsx('w-3.5 h-3.5 shrink-0', active ? 'text-[#D4AF37]' : 'text-[#8B949E] group-hover:text-[#D4AF37]')} />
      
      <span className="font-semibold text-[#D4AF37] shrink-0">#{index}</span>
      
      <span className="truncate max-w-[140px] sm:max-w-[200px] text-left">
        {title}
        {heading ? ` (${heading})` : page ? ` (p. ${page})` : ''}
      </span>

      {confidencePct !== null && (
        <span
          className={clsx(
            'px-1.5 py-0.5 rounded text-[10px] font-semibold shrink-0 ml-1',
            confidencePct >= 80
              ? 'bg-[#00E676]/15 text-[#00E676] border border-[#00E676]/30'
              : confidencePct >= 60
              ? 'bg-[#FFA726]/15 text-[#FFA726] border border-[#FFA726]/30'
              : 'bg-[#8B949E]/15 text-[#8B949E] border border-[#8B949E]/30'
          )}
        >
          {confidencePct}%
        </span>
      )}

      <ChevronRight className={clsx('w-3 h-3 shrink-0 opacity-40 group-hover:opacity-100 transition-opacity', active && 'opacity-100 text-[#D4AF37]')} />
    </button>
  );
};
