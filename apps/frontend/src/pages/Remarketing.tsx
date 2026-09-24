import RemarketingCard from "../components/config/RemarketingCard";
import { Link } from "react-router-dom";

export default function Remarketing() {
  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Remarketing</h2>
          <div className="subtitle">
            Clientes do portal Renegocie: filtros por segmento e prévia de quem entraria. A conexão com o Renegocie
            fica em <Link to="/configuracoes">Configurações → Conexões</Link>.
          </div>
        </div>
      </div>

      <RemarketingCard />
    </div>
  );
}
