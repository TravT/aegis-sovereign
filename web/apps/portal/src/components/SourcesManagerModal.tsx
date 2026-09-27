'use client';

import React, { useState } from 'react';
import { FolderOpen, ShieldCheck, Plus, RefreshCw, Trash2, Check, AlertTriangle } from 'lucide-react';
import { Modal, Button, Badge } from '@aegis/ui';
import { MonitoredSourceRecord } from '@/types';

export interface SourcesManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  sources: MonitoredSourceRecord[];
  onAddSource: (path: string, domain: string) => Promise<void>;
  onPurgeSource: (path: string) => Promise<void>;
  onResyncSource?: (path: string, domain: string) => Promise<void>;
}

export const SourcesManagerModal: React.FC<SourcesManagerModalProps> = ({
  isOpen,
  onClose,
  sources,
  onAddSource,
  onPurgeSource,
  onResyncSource,
}) => {
  const [newPath, setNewPath] = useState<string>('');
  const [newDomain, setNewDomain] = useState<string>('Custom Server Corpus');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [purgingPath, setPurgingPath] = useState<string | null>(null);
  const [feedbackMsg, setFeedbackMsg] = useState<string | null>(null);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPath.trim()) return;
    setIsSubmitting(true);
    try {
      await onAddSource(newPath.trim(), newDomain.trim());
      setNewPath('');
      setFeedbackMsg(`Diretório '${newPath}' adicionado com sucesso!`);
      setTimeout(() => setFeedbackMsg(null), 3000);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handlePurge = async (path: string) => {
    if (!window.confirm(`Tem certeza que deseja expurgar os registros indexados de '${path}' do banco de dados?`)) {
      return;
    }
    setPurgingPath(path);
    try {
      await onPurgeSource(path);
      setFeedbackMsg(`Registros de '${path}' expurgados com sucesso!`);
      setTimeout(() => setFeedbackMsg(null), 3000);
    } finally {
      setPurgingPath(null);
    }
  };

  const maxRecords = Math.max(1, ...sources.map((s) => Number(s.indexed_records || 0)));

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="MONITORED SERVER DIRECTORIES &amp; PURGE MANAGER"
      subtitle="Manage server paths indexed into SQLite B-Tree router and 1-click purge database records"
      icon={<FolderOpen className="w-5 h-5 text-[#D4AF37]" />}
      maxWidth="3xl"
    >
      <div className="space-y-5 text-xs text-[#E6EDF3]">
        {/* Anti-Loop Sentinel Banner */}
        <div className="p-3 rounded-lg bg-[#07090D] border border-[#00E676]/30 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-[#00E676] shrink-0" />
            <span className="text-[11px] font-mono text-[#A7F3D0]">
              Anti-Loop Sentinel: .aegis-no-index Ouroboros Guardrail Ativo
            </span>
          </div>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#00E676]/10 text-[#00E676] border border-[#00E676]/30">
            PROTEÇÃO CONTRA RECURSÃO
          </span>
        </div>

        {/* Feedback Message */}
        {feedbackMsg && (
          <div className="p-2.5 rounded bg-[#D4AF37]/15 border border-[#D4AF37]/40 text-[#F3E5AB] font-mono text-[11px] flex items-center gap-2">
            <Check className="w-3.5 h-3.5 text-[#00E676]" />
            <span>{feedbackMsg}</span>
          </div>
        )}

        {/* Add Directory Form */}
        <form onSubmit={handleAdd} className="p-3.5 rounded-lg bg-[#141A24] border border-[#232B38] space-y-3">
          <p className="font-mono text-[10px] text-[#D4AF37] uppercase font-semibold">
            ➕ Adicionar Novo Diretório do Servidor para Monitoramento
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-12 gap-2">
            <div className="sm:col-span-7">
              <input
                type="text"
                value={newPath}
                onChange={(e) => setNewPath(e.target.value)}
                placeholder="/home/tlima/Enterprise_Hub/docs/wiki/operations"
                required
                className="w-full px-3 py-2 bg-[#0E121A] border border-[#232B38] rounded text-xs text-[#E6EDF3] placeholder-[#8B949E] focus:outline-none focus:border-[#D4AF37]"
              />
            </div>
            <div className="sm:col-span-3">
              <input
                type="text"
                value={newDomain}
                onChange={(e) => setNewDomain(e.target.value)}
                placeholder="Rótulo de Domínio"
                className="w-full px-3 py-2 bg-[#0E121A] border border-[#232B38] rounded text-xs text-[#E6EDF3] placeholder-[#8B949E] focus:outline-none focus:border-[#D4AF37]"
              />
            </div>
            <div className="sm:col-span-2">
              <Button
                type="submit"
                variant="gold"
                size="md"
                className="w-full h-full text-xs"
                loading={isSubmitting}
              >
                Ingerir
              </Button>
            </div>
          </div>
        </form>

        {/* Monitored Directories Table */}
        <div className="border border-[#232B38] rounded-lg overflow-x-auto shadow-inner bg-[#07090D]">
          <table className="w-full border-collapse text-left text-xs">
            <thead className="bg-[#0E121A] border-b border-[#232B38]">
              <tr>
                <th className="px-3.5 py-2 font-mono text-[11px] font-bold text-[#F3E5AB]">Diretório no Servidor</th>
                <th className="px-3.5 py-2 font-mono text-[11px] font-bold text-[#F3E5AB]">Domínio</th>
                <th className="px-3.5 py-2 font-mono text-[11px] font-bold text-[#F3E5AB]">Registros</th>
                <th className="px-3.5 py-2 font-mono text-[11px] font-bold text-[#F3E5AB]">Ações</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#232B38]/60 font-sans">
              {sources.map((s, idx) => {
                const count = Number(s.indexed_records || 0);
                const pct = Math.min(100, Math.max(8, Math.round((count / maxRecords) * 100)));
                const isPurging = purgingPath === s.path;

                return (
                  <tr key={idx} className="hover:bg-white/[0.02] transition-colors">
                    <td className="px-3.5 py-2.5 font-mono text-[11px] text-[#E6EDF3]">
                      <code>{s.path}</code>
                    </td>
                    <td className="px-3.5 py-2.5 text-[#8B949E]">
                      <span className="px-2 py-0.5 rounded bg-[#141A24] border border-[#232B38] text-[10px] font-mono">
                        {s.domain}
                      </span>
                    </td>
                    <td className="px-3.5 py-2.5 font-mono">
                      <div className="text-[11px] text-[#00E676] font-semibold">
                        {count.toLocaleString()} registros
                      </div>
                      <div className="w-24 h-1.5 rounded-full bg-[#141A24] mt-1 overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-[#00E676] to-[#D4AF37]"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </td>
                    <td className="px-3.5 py-2.5">
                      <div className="flex items-center gap-1.5">
                        {onResyncSource && (
                          <button
                            type="button"
                            onClick={() => onResyncSource(s.path, s.domain)}
                            className="p-1 rounded bg-[#141A24] border border-[#232B38] hover:border-[#00E676] text-[#8B949E] hover:text-[#00E676] transition-colors"
                            title="Re-sincronizar diretório"
                          >
                            <RefreshCw className="w-3.5 h-3.5" />
                          </button>
                        )}
                        <button
                          type="button"
                          disabled={isPurging}
                          onClick={() => handlePurge(s.path)}
                          className="px-2 py-1 rounded bg-[#FF5252]/10 border border-[#FF5252]/30 hover:bg-[#FF5252]/20 text-[#FF5252] font-mono text-[10px] flex items-center gap-1 transition-colors"
                          title="Expurgar registros deste diretório com 1 clique"
                        >
                          <Trash2 className="w-3 h-3" />
                          <span>{isPurging ? 'Expurgando...' : 'Expurgar'}</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </Modal>
  );
};
