import { useEffect, useState } from "react";
import { api, FiltrosLoja, Loja, RegrasCobranca } from "../api";

export interface Opcao {
  value: string;
  label: string;
}

export interface OpcoesCobranca {
  regras: RegrasCobranca | null;
  lojas: Opcao[];
  regionais: Opcao[];
  estados: Opcao[];
  clustersInad: Opcao[];
  clustersPopulacao: Opcao[];
  // Sem a conta Google conectada, /lojas responde 503: os filtros por
  // atributo de loja ficam desligados e a loja vira campo de texto.
  googleIndisponivel: boolean;
}

const paraOpcoes = (valores: string[] = []): Opcao[] => valores.map((v) => ({ value: v, label: v }));

export function useOpcoesCobranca(): OpcoesCobranca {
  const [regras, setRegras] = useState<RegrasCobranca | null>(null);
  const [lojas, setLojas] = useState<Loja[]>([]);
  const [filtrosLoja, setFiltrosLoja] = useState<FiltrosLoja | null>(null);
  const [googleIndisponivel, setGoogleIndisponivel] = useState(false);

  useEffect(() => {
    api.regrasCobranca().then(setRegras).catch(() => {});
    api.listarLojas().then(setLojas).catch(() => setGoogleIndisponivel(true));
    api.filtrosLojas().then(setFiltrosLoja).catch(() => setGoogleIndisponivel(true));
  }, []);

  return {
    regras,
    lojas: lojas.map((l) => ({ value: l.filial, label: l.nome_com_cod ?? l.filial })),
    regionais: paraOpcoes(filtrosLoja?.regionais),
    estados: paraOpcoes(filtrosLoja?.estados),
    clustersInad: paraOpcoes(filtrosLoja?.clusters_inad),
    clustersPopulacao: paraOpcoes(filtrosLoja?.clusters_populacao),
    googleIndisponivel,
  };
}
