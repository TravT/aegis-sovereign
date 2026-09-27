'use client';

import React from 'react';
import { Zap, Brain, Terminal, Server } from 'lucide-react';

export interface PresetChipsProps {
  onSelectPreset: (presetText: string) => void;
  className?: string;
}

interface ChipItem {
  id: string;
  label: string;
  query: string;
  subtitle?: string;
}

const PRONG1_HOMELAB: ChipItem[] = [
  { id: 'adr-40', label: 'ADR-40', query: 'ADR-40', subtitle: 'Two-Pronged Architecture' },
  { id: 'adr-30', label: 'ADR-30', query: 'ADR-30', subtitle: 'Smart Home Zigbee 3.0' },
  { id: 'manage-traefik', label: 'manage-traefik', query: 'manage-traefik', subtitle: 'Nomad Dynamic Tags' },
];

const PRONG1_TELECOM: ChipItem[] = [
  { id: 'alm-20104', label: 'ALM-20104', query: 'ALM-20104', subtitle: 'Link Bear Quality Drop' },
  { id: 'alm-1003', label: 'ALM-1003', query: 'ALM-1003', subtitle: 'Module Fault + Root Diagram' },
  { id: 'dsp-optmodule', label: 'DSP OPTMODULE', query: 'DSP OPTMODULE', subtitle: 'MML Optical Command' },
  { id: 'lote-202609b', label: 'LOTE-202609B', query: 'LOTE-202609B', subtitle: 'ANVISA Batch Trace' },
];

const PRONG2_SYNTHESIS: ChipItem[] = [
  {
    id: 'traefik-routing',
    label: 'Homelab Traefik Ingress Routing',
    query: 'How is Traefik ingress routed in the homelab?',
    subtitle: 'Cluster ingress invariants & ports',
  },
  {
    id: 'usc-pods',
    label: 'USC POD Architecture',
    query: 'How are the PODs of the USC organized?',
    subtitle: 'Cloud plane microservice tiers',
  },
];

export const PresetChips: React.FC<PresetChipsProps> = ({
  onSelectPreset,
  className = '',
}) => {
  return (
    <div className={`space-y-3 ${className}`}>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {/* Group 1: Prong 1 Homelab */}
        <div className="p-3 rounded-lg bg-[#0E121A] border border-[#232B38] space-y-2">
          <div className="flex items-center justify-between text-xs font-mono">
            <span className="flex items-center gap-1.5 text-[#00E676] font-semibold">
              <Server className="w-3.5 h-3.5" />
              <span>PRONG 1 HOMELAB</span>
            </span>
            <span className="text-[10px] text-[#8B949E]">&lt;2ms Exact</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {PRONG1_HOMELAB.map((chip) => (
              <button
                key={chip.id}
                type="button"
                onClick={() => onSelectPreset(chip.query)}
                className="group px-2.5 py-1.5 rounded bg-[#141A24] border border-[#232B38] hover:border-[#00E676]/60 hover:bg-[#1A2230] text-left transition-all"
                title={chip.subtitle}
              >
                <div className="flex items-center gap-1.5">
                  <code className="text-xs font-mono font-bold text-[#00E676] group-hover:text-[#A7F3D0]">
                    [{chip.label}]
                  </code>
                </div>
                {chip.subtitle && (
                  <p className="text-[10px] text-[#8B949E] group-hover:text-[#E6EDF3] truncate max-w-[140px]">
                    {chip.subtitle}
                  </p>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Group 2: Prong 1 Telecom */}
        <div className="p-3 rounded-lg bg-[#0E121A] border border-[#232B38] space-y-2">
          <div className="flex items-center justify-between text-xs font-mono">
            <span className="flex items-center gap-1.5 text-[#D4AF37] font-semibold">
              <Zap className="w-3.5 h-3.5" />
              <span>PRONG 1 TELECOM</span>
            </span>
            <span className="text-[10px] text-[#8B949E]">0 Tokens</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {PRONG1_TELECOM.map((chip) => (
              <button
                key={chip.id}
                type="button"
                onClick={() => onSelectPreset(chip.query)}
                className="group px-2.5 py-1.5 rounded bg-[#141A24] border border-[#232B38] hover:border-[#D4AF37]/60 hover:bg-[#1A2230] text-left transition-all"
                title={chip.subtitle}
              >
                <div className="flex items-center gap-1.5">
                  <code className="text-xs font-mono font-bold text-[#F3E5AB] group-hover:text-white">
                    [{chip.label}]
                  </code>
                </div>
                {chip.subtitle && (
                  <p className="text-[10px] text-[#8B949E] group-hover:text-[#E6EDF3] truncate max-w-[130px]">
                    {chip.subtitle}
                  </p>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Group 3: Prong 2 Semantic & Synthesis */}
        <div className="p-3 rounded-lg bg-[#0E121A] border border-[#232B38] space-y-2">
          <div className="flex items-center justify-between text-xs font-mono">
            <span className="flex items-center gap-1.5 text-[#2979FF] font-semibold">
              <Brain className="w-3.5 h-3.5" />
              <span>PRONG 2 SYNTHESIS</span>
            </span>
            <span className="text-[10px] text-[#8B949E]">NanoRunner + Graph</span>
          </div>
          <div className="flex flex-col gap-1.5">
            {PRONG2_SYNTHESIS.map((chip) => (
              <button
                key={chip.id}
                type="button"
                onClick={() => onSelectPreset(chip.query)}
                className="group px-2.5 py-1.5 rounded bg-[#141A24] border border-[#232B38] hover:border-[#2979FF]/60 hover:bg-[#1A2230] text-left transition-all"
              >
                <div className="flex items-center justify-between">
                  <code className="text-xs font-mono text-[#82B1FF] group-hover:text-white truncate">
                    {chip.label}
                  </code>
                </div>
                <p className="text-[10px] text-[#8B949E] group-hover:text-[#E6EDF3] truncate">
                  &ldquo;{chip.query}&rdquo;
                </p>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
