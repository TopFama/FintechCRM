import { useEffect, useState } from "react";
import { api, DispatchConfig, Faixa } from "../../api";
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

// Agendamento de disparo (dias, janela, intervalo, lote) de cada envio
// (número + template) de cada faixa — cada envio roda com sua própria
// configuração, pensado pra WABAs diferentes cobrando em paralelo.
export default function DisparoCard() {
  const [faixas, setFaixas] = useState<Faixa[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [editandoEnvioId, setEditandoEnvioId] = useState<string | null>(null);
  const [edicao, setEdicao] = useState<DispatchConfig | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [dispatchMsg, setDispatchMsg] = useState<Record<string, string>>({});
  const [disparando, setDisparando] = useState<string | null>(null);

  function carregar() {
    api.listFaixas().then(setFaixas).catch((e) => setErro(e.message));
  }

  useEffect(carregar, []);

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
        schedule_days: edicao.schedule_days,
        schedule_start: edicao.schedule_start,
        schedule_end: edicao.schedule_end,
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
    <div className="card">
      <div className="card-header">
        <div>
          <h3>Disparo</h3>
          <div className="card-subtitle">
            Agendamento (dias, horário, intervalo entre rodadas) de cada número/template de cada faixa — controla
            quando e com que ritmo o worker processa a fila. Horários são no fuso de Brasília.
          </div>
        </div>
      </div>

      {erro && (
        <div className="error-box" style={{ marginBottom: 16 }}>
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}

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
                    <th>Dias</th>
                    <th>Janela</th>
                    <th>Intervalo</th>
                    <th>Lote</th>
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
                          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                            {WEEKDAYS.map((d) => {
                              const ativo = edicao.schedule_days.split(",").includes(d.value);
                              return (
                                <button
                                  key={d.value}
                                  type="button"
                                  className={ativo ? "small" : "secondary small"}
                                  onClick={() =>
                                    setEdicao({ ...edicao, schedule_days: toggleWeekday(edicao.schedule_days, d.value) })
                                  }
                                >
                                  {d.label}
                                </button>
                              );
                            })}
                          </div>
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 4 }}>
                            <input
                              aria-label="Início"
                              style={{ width: 70 }}
                              value={edicao.schedule_start}
                              onChange={(ev) => setEdicao({ ...edicao, schedule_start: ev.target.value })}
                            />
                            <input
                              aria-label="Fim"
                              style={{ width: 70 }}
                              value={edicao.schedule_end}
                              onChange={(ev) => setEdicao({ ...edicao, schedule_end: ev.target.value })}
                            />
                          </div>
                        </td>
                        <td>
                          <input
                            aria-label="Intervalo em segundos"
                            type="number"
                            style={{ width: 70 }}
                            value={edicao.interval_seconds}
                            onChange={(ev) => setEdicao({ ...edicao, interval_seconds: Number(ev.target.value) })}
                          />
                        </td>
                        <td>
                          <input
                            aria-label="Cobranças por rodada"
                            type="number"
                            style={{ width: 60 }}
                            value={edicao.batch_size}
                            onChange={(ev) => setEdicao({ ...edicao, batch_size: Number(ev.target.value) })}
                          />
                        </td>
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
                        <td className="text-muted">
                          {e.dispatch_config
                            ? WEEKDAYS.filter((d) => e.dispatch_config!.schedule_days.split(",").includes(d.value))
                                .map((d) => d.label)
                                .join(", ") || "—"
                            : "—"}
                        </td>
                        <td className="text-muted">
                          {e.dispatch_config ? `${e.dispatch_config.schedule_start}–${e.dispatch_config.schedule_end}` : "—"}
                        </td>
                        <td className="text-muted">{e.dispatch_config ? `${e.dispatch_config.interval_seconds}s` : "—"}</td>
                        <td className="text-muted">{e.dispatch_config?.batch_size ?? "—"}</td>
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
  );
}
