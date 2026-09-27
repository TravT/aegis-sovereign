'use client';

import React from 'react';
import { Globe, Home, Radio } from 'lucide-react';
import { DomainScope } from '@/types';

export interface DomainFilterBarProps {
  activeDomain: DomainScope;
  onSelectDomain: (domain: DomainScope) => void;
  className?: string;
}

interface DomainOption {
  id: DomainScope;
  label: string;
  icon: React.ReactNode;
  description: string;
  badge?: string;
}

const DOMAIN_OPTIONS: DomainOption[] = [
  {
    id: 'all',
    label: 'All Vaults',
    icon: <Globe className="w-3.5 h-3.5" />,
    description: 'Unified cross-vault retrieval & entity reconciliation',
    badge: 'ALL',
  },
  {
    id: 'homelab',
    label: 'Homelab Operations',
    icon: <Home className="w-3.5 h-3.5" />,
    description: 'ADRs, Nomad jobs, Traefik routes & cluster runbooks',
    badge: 'HOMELAB',
  },
  {
    id: 'telecom',
    label: 'Telecom Vendor Catalog',
    icon: <Radio className="w-3.5 h-3.5" />,
    description: 'Huawei USC/UPCF 26.1.0 alarms, MML specs & signaling docs',
    badge: 'TELECOM',
  },
];

export const DomainFilterBar: React.FC<DomainFilterBarProps> = ({
  activeDomain,
  onSelectDomain,
  className = '',
}) => {
  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      <span className="text-[11px] font-mono uppercase tracking-wider text-[#8B949E] mr-1 flex items-center gap-1.5">
        <span>Domain Scope:</span>
      </span>

      <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-lg bg-[#0E121A] border border-[#232B38]">
        {DOMAIN_OPTIONS.map((opt) => {
          const isActive = activeDomain === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => onSelectDomain(opt.id)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-mono transition-all select-none ${
                isActive
                  ? 'bg-gradient-to-r from-[#D4AF37]/25 to-[#D4AF37]/10 text-[#F3E5AB] border border-[#D4AF37] shadow-[0_0_12px_rgba(212,175,55,0.25)] font-semibold'
                  : 'bg-transparent text-[#8B949E] hover:text-[#E6EDF3] hover:bg-[#141A24] border border-transparent'
              }`}
              title={opt.description}
            >
              <span className={isActive ? 'text-[#D4AF37]' : 'text-[#8B949E]'}>
                {opt.icon}
              </span>
              <span>{opt.label}</span>
              <span
                className={`text-[9px] px-1 py-0.5 rounded font-mono ${
                  isActive
                    ? 'bg-[#D4AF37]/20 text-[#F3E5AB] border border-[#D4AF37]/40'
                    : 'bg-[#141A24] text-[#8B949E]/70'
                }`}
              >
                {opt.badge}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
};
