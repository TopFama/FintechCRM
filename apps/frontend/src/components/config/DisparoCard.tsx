import { useEffect, useState } from "react";
import { api, DispatchConfig, Faixa, GlobalDispatchConfig } from "../../api";
import { IconAlert, IconBolt, IconCheckCircle } from "../../icons";

const WEEKDAYS = [
  { value: "1", label: "Seg" },
  { value: "2", label: "Ter" },
  { value: "3", label: "Qua" },
  { value: "4", label: "Qui" },
  { value: "5", label: "Sex" },
  { value: "6", label: "Sáb" },
  { value: "7", label: "Dom" },
];

function toggleWeekday(scheduleDays: string, value: string): string {
  const days = new Set(scheduleDays.split(",").filter(Boolean));
  if (days.has(value)) {
    days.delete(value);
  } else {
    days.add(value);
  }
  return WEEKDAYS.map((d) => d.value).filter((v) => days.has(v)).join(",");
}

// Janela de disparo (dias, horário), ritmo (intervalo e quantidade por vez)
// e extração automática de leads são globais — valem pra todo envio de toda
// faixa. Só ativo/inativo continua por envio (número + template).
export default function DisparoCard() {
  const [faixas, setFaixas] = useState<Faixa[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [editandoEnvioId, setEditandoEnvioId] = useState<string | null>(null);
  const [edicao, setEdicao] = useState<DispatchConfig | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [dispatchMsg, setDispatchMsg] = useState<Record<string, string>>({});
  const [disparando, setDisparando] = useState<string | null>(null);

  const [globalConfig, setGlobalConfig] = useState<GlobalDispatchConfig | null>(null);
  const [editandoGlobal, setEditandoGlobal] = useState(false);
  const [edicaoGlobal, setEdicaoGlobal] = useState<GlobalDispatchConfig | null>(null);
  const [salvandoGlobal, setSalvandoGlobal] = useState(false);

  function carregar() {
    api.listFaixas().then(setFaixas).catch((e) => setErro(e.message));
    api.getGlobalDispatchConfig().then(setGlobalConfig).catch((e) => setErro(e.message));
  }

  useEffect(carregar, []);

  function editarGlobal() {
    if (!globalConfig) return;
    setErro(null);
    setEdicaoGlobal({ ...globalConfig });
    setEditandoGlobal(true);
  }

  async function salvarGlobal() {
    if (!edicaoGlobal) return;
    setErro(null);
    setSalvandoGlobal(true);
    try {
      const atualizado = await api.updateGlobalDispatchConfig({
        schedule_days: edicaoGlobal.schedule_days,
        schedule_start: edicaoGlobal.schedule_start,
        schedule_end: edicaoGlobal.schedule_end,
        leads_auto_extract: edicaoGlobal.leads_auto_extract,
        leads_auto_extract_minutos_antes: edicaoGlobal.leads_auto_extract_minutos_antes,
        interval_seconds: edicaoGlobal.interval_seconds,
        batch_size: edicaoGlobal.batch_size,
      });
      setGlobalConfig(atualizado);
      setEditandoGlobal(false);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao salvar horário de disparo");
    } finally {
      setSalvandoGlobal(false);
    }
  }

  function editar(faixaId: string, envioId: string, config: DispatchConfig) {
    setErro(null);
    setEditandoEnvioId(`${faixaId}:${envioId}`);
    setEdicao({ ...config });
  }

  async function salvar(faixaId: string, envioId: string) {
    if (!edicao) return;
    setErro(null);
    setSalvando(true);
    try {
      await api.updateDispatchConfig(faixaId, envioId, {
        interval_seconds: edicao.interval_seconds,
        batch_size: edicao.batch_size,
        active: edicao.active,
      });
      setEditandoEnvioId(null);
      carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao salvar configuração de disparo");
    } finally {
      setSalvando(false);
    }
  }

  async function cobrarAgora(faixa: Faixa) {
    setErro(null);
    setDisparando(faixa.id);
    setDispatchMsg((m) => ({ ...m, [faixa.id]: "" }));
    try {
      await api.dispatchNow(faixa.id);
      setDispatchMsg((m) => ({ ...m, [faixa.id]: "Disparo agendado — o worker vai processar na próxima varredura." }));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao disparar agora");
    } finally {
      setDisparando(null);
    }
  }

  const faixasComEnvio = faixas.filter((f) => f.envios.length > 0);

  return (
    <>
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-header">
          <div>
            <h3>Horário de disparo</h3>
            <div className="card-subtitle">
              Janela global (dias e horário) em que o worker cobra — vale para todas as faixas e envios. Horários são
              no fuso de Brasília.
            </div>
          </div>
          {!editandoGlobal && (
            <button type="button" className="secondary small" onClick={editarGlobal} disabled={!globalConfig}>
              Editar
            </button>
          )}
        </div>

        {erro && (
          <div className="error-box" style={{ marginBottom: 16 }}>
            <IconAlert width={16} height={16} />
            <span>{erro}</span>
          </div>
        )}

        {globalConfig && editandoGlobal && edicaoGlobal ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <label style={{ display: "block", marginBottom: 4 }}>Dias</label>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {WEEKDAYS.map((d) => {
                  const ativo = edicaoGlobal.schedule_days.split(",").includes(d.value);
                  return (
                    <button
                      key={d.value}
                      type="button"
                      className={ativo ? "small" : "secondary small"}
                      onClick={() =>
                        setEdicaoGlobal({ ...edicaoGlobal, schedule_days: toggleWeekday(edicaoGlobal.schedule_days, d.value) })
                      }
                    >
                      {d.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="form-row">
              <label>
                Início
                <input
                  value={edicaoGlobal.schedule_start}
                  onChange={(ev) => setEdicaoGlobal({ ...edicaoGlobal, schedule_start: ev.target.value })}
                />
              </label>
              <label>
                Fim
                <input
                  value={edicaoGlobal.schedule_end}
                  onChange={(ev) => setEdicaoGlobal({ ...edicaoGlobal, schedule_end: ev.target.value })}
                />
              </label>
            </div>
            <div className="form-row">
              <label>
                Intervalo entre rodadas (segundos)
                <input
                  type="number"
                  min={1}
                  value={edicaoGlobal.interval_seconds}
                  onChange={(ev) => setEdicaoGlobal({ ...edicaoGlobal, interval_seconds: Number(ev.target.value) })}
                />
              </label>
              <label>
                Mensagens por vez
                <input
                  type="number"
                  min={1}
                  value={edicaoGlobal.batch_size}
                  onChange={(ev) => setEdicaoGlobal({ ...edicaoGlobal, batch_size: Number(ev.target.value) })}
                />
              </label>
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={edicaoGlobal.leads_auto_extract}
                onChange={(ev) => setEdicaoGlobal({ ...edicaoGlobal, leads_auto_extract: ev.target.checked })}
              />
              Extrair leads automaticamente pouco antes do disparo começar
            </label>
            {edicaoGlobal.leads_auto_extract && (
              <div className="field-hint">
                Nos dias selecionados, os clientes no primeiro dia da faixa (pela regra do WhatsApp) entram sozinhos na
                fila e são cobrados a partir do início. O que não for enviado até o fim da janela é excluído.
              </div>
            )}
            {edicaoGlobal.leads_auto_extract && (
              <label style={{ maxWidth: 260 }}>
                Minutos antes do início
                <input
                  type="number"
                  min={0}
                  max={240}
                  value={edicaoGlobal.leads_auto_extract_minutos_antes}
                  onChange={(ev) =>
                    setEdicaoGlobal({ ...edicaoGlobal, leads_auto_extract_minutos_antes: Number(ev.target.value) })
                  }
                />
              </label>
            )}
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" onClick={salvarGlobal} disabled={salvandoGlobal}>
                {salvandoGlobal ? "Salvando..." : "Salvar"}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setEditandoGlobal(false)}
                disabled={salvandoGlobal}
              >
                Cancelar
              </button>
            </div>
          </div>
        ) : globalConfig ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div>
              <strong>Dias: </strong>
              {WEEKDAYS.filter((d) => globalConfig.schedule_days.split(",").includes(d.value))
                .map((d) => d.label)
                .join(", ") || "—"}
            </div>
            <div>
              <strong>Janela: </strong>
              {globalConfig.schedule_start}–{globalConfig.schedule_end}
            </div>
            <div>
              <strong>Ritmo: </strong>
              {globalConfig.batch_size} mensagem(ns) a cada {globalConfig.interval_seconds}s por envio
            </div>
            <div>
              <strong>Extração automática de leads: </strong>
              {globalConfig.leads_auto_extract
                ? `Sim, ${globalConfig.leads_auto_extract_minutos_antes} min antes do início`
                : "Não"}
            </div>
          </div>
        ) : (
          <p className="text-muted">Carregando...</p>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <h3>Disparo por envio</h3>
            <div className="card-subtitle">
              Ativo/inativo de cada número/template de cada faixa. O ritmo de envio é o geral, definido acima.
            </div>
          </div>
        </div>

        {faixasComEnvio.length === 0 ? (
          <p className="text-muted">
            Nenhuma faixa com número/template atribuído ainda — atribua em Faixas de cobrança.
          </p>
        ) : (
          faixasComEnvio.map((f) => (
            <div key={f.id} style={{ marginBottom: 24 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <h4 style={{ margin: 0 }}>{f.name}</h4>
                <button
                  type="button"
                  className="secondary small"
                  onClick={() => cobrarAgora(f)}
                  disabled={disparando === f.id}
                >
                  <IconBolt width={14} height={14} /> {disparando === f.id ? "Disparando..." : "Cobrar esta base agora"}
                </button>
              </div>
              {dispatchMsg[f.id] && (
                <div className="success-box" style={{ marginBottom: 10 }}>
                  <IconCheckCircle width={16} height={16} />
                  <span>{dispatchMsg[f.id]}</span>
                </div>
              )}
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Número</th>
                      <th>Template</th>
                      <th>Ativo</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {f.envios.map((e) => {
                      const chave = `${f.id}:${e.id}`;
                      return editandoEnvioId === chave && edicao ? (
                        <tr key={e.id}>
                          <td className="cell-strong">{e.whatsapp_number.label || e.whatsapp_number.display_phone_number}</td>
                          <td>{e.template.name}</td>
                          <td>
                            <select
                              aria-label="Ativo"
                              value={edicao.active ? "sim" : "nao"}
                              onChange={(ev) => setEdicao({ ...edicao, active: ev.target.value === "sim" })}
                            >
                              <option value="sim">Sim</option>
                              <option value="nao">Não</option>
                            </select>
                          </td>
                          <td style={{ display: "flex", gap: 6 }}>
                            <button type="button" className="small" onClick={() => salvar(f.id, e.id)} disabled={salvando}>
                              {salvando ? "Salvando..." : "Salvar"}
                            </button>
                            <button
                              type="button"
                              className="secondary small"
                              onClick={() => setEditandoEnvioId(null)}
                              disabled={salvando}
                            >
                              Cancelar
                            </button>
                          </td>
                        </tr>
                      ) : (
                        <tr key={e.id}>
                          <td className="cell-strong">{e.whatsapp_number.label || e.whatsapp_number.display_phone_number}</td>
                          <td>{e.template.name}</td>
                          <td>
                            <span className={`status-pill ${e.dispatch_config?.active ? "on" : "off"}`}>
                              {e.dispatch_config?.active ? "Sim" : "Não"}
                            </span>
                          </td>
                          <td>
                            <button
                              type="button"
                              className="secondary small"
                              disabled={!e.active || !e.dispatch_config}
                              title={!e.active ? "Envio inativo — reative em Faixas" : undefined}
                              onClick={() => e.dispatch_config && editar(f.id, e.id, e.dispatch_config)}
                            >
                              Editar
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))
        )}
      </div>
    </>
  );
}
