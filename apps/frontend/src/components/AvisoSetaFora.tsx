import { useState, useSyncExternalStore } from "react";
import { api, setaFora } from "../api";
import { formatDataHora } from "../format";
import { IconAlert } from "../icons";

/** Desde quando o SETA está sem conexão (null = conectado ou sem falha recente). */
export function useSetaFora(): string | null {
  return useSyncExternalStore(setaFora.ouvir, setaFora.desde);
}

// Faixa no topo de todas as telas. Só aparece depois de uma consulta real falhar
// (tela ou rotina); "Testar conexão" é o único teste ao SETA, e só no clique.
export default function AvisoSetaFora() {
  const desde = useSetaFora();
  const [testando, setTestando] = useState(false);
  if (!desde) return null;
  return (
    <div className="warning-box aviso-seta-fora" role="alert">
      <IconAlert width={16} height={16} />
      <span>Sem conexão com o SETA desde {formatDataHora(desde)}.</span>
      <button
        type="button"
        className="secondary small"
        disabled={testando}
        onClick={() => {
          setTestando(true);
          api
            .statusSeta()
            .catch(() => undefined)
            .finally(() => setTestando(false));
        }}
      >
        {testando ? "Testando..." : "Testar conexão"}
      </button>
    </div>
  );
}
