# Herdr Quota Monitor

Monitor minimalista y en tiempo real para terminales y agentes en **Herdr**.

Diseñado para integrarse de forma limpia y sobria en la barra de estado inferior de Herdr, mostrando las métricas exactas del proyecto y terminal que estés usando en cada momento.

```text
🖥️ This computer  branch main │ ● Gemini 3.8 Flash  tok: 18.7M  ctx: 207k/1.0M (20.8%) │ 5h: 65% · 24m  sem: 56% │ commands
```

---

## Glosario de Métricas: ¿Cómo interpretar los datos?

Para entender exactamente qué significa cada número en tu barra inferior:

| Indicador | Ejemplo | Significado |
|---|---|---|
| **Modelo Activo** | `● Gemini 3.8 Flash` | El modelo de Inteligencia Artificial que está procesando la terminal actual. |
| **`tok:` (Tokens de Sesión)** | `tok: 18.7M` | Cantidad total acumulada de tokens procesados en la conversación del proyecto activo (Prompt + Respuesta + Lectura de Caché). `k` = miles, `M` = millones. |
| **`ctx:` (Ventana de Contexto)** | `ctx: 207k/1.0M (20.8%)` | **Contexto actual ocupado frente al límite máximo del modelo**. Indica cuánta memoria de conversación tiene cargada en este turno específico y qué porcentaje representa del límite total admitido (ej. 1 millón en Gemini Flash). Te permite saber si estás cerca del límite de compactación del modelo. |
| **`5h:` (Cuota de 5 Horas)** | `5h: 65% · 24m` | **Porcentaje disponible que te queda** en tu ventana deslizante de 5 horas. El valor posterior (`· 24m`) indica el tiempo exacto que falta para que el turno más antiguo de la ventana expire y tu cuota comience a recuperarse. |
| **`sem:` (Cuota Semanal)** | `sem: 56%` | **Porcentaje disponible que te queda** de tu presupuesto semanal de uso oficial de tu cuenta o plan. |

### Código de Colores de Cuota:
- **Color atenuado / normal**: Cuota saludable (más del 30% restante).
- **Amarillo**: Atención (te queda entre el 15% y 30%).
- **Rojo**: Cuota crítica (menos del 15% restante).

---

## Características Principales

1. **Soporte Multisesión y Multiterminal**:
   - Cambia dinámicamente entre pestañas y espacios de Herdr. Si pasas de un proyecto `Frontend` a uno `Backend`, los contadores de `tok` y `ctx` cambian instantáneamente para reflejar ese proyecto en específico.

2. **Cero Latencia (Zero-Polling)**:
   - Utiliza el motor nativo de eventos de sistema de archivos de Herdr (`watchFolder`). En cuanto el agente genera tokens o actualiza su estado, la barra se repinta en menos de 16 milisegundos.

3. **Arquitectura Universal de Adaptadores**:
   - **Antigravity**: Consulta oficial sincronizada con el backend local (`RetrieveUserQuotaSummary`).
   - **Claude Code**: Adaptador para consumo y límites de `~/.claude/`.
   - **Open Standard**: Cualquier CLI o agente propio puede emitir métricas escribiendo un JSON en `~/.config/herdr-app/data/custom_agent_quota.json`.

---

## Instalación

### Método 1: Instalador Automático (Windows)
Haz doble clic en `install.bat` o ejecuta en PowerShell:
```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### Método 2: Con un Agente de Herdr
Indícale a tu agente dentro de Herdr:
```text
Lee RECIPE.md de este repositorio e instala el mod herdr-quota-monitor.
```

### Método 3: Instalación Manual
1. Copia `main.js`, `mod.json` y `collector.py` dentro de:
   `~/.config/herdr-app/mods/agent-quota-bar/`
2. Copia `main.js` también en:
   `~/.config/herdr-app/mods/workspace-status/main.js`
3. Ejecuta una vez el recolector para sembrar los datos iniciales:
   ```bash
   python ~/.config/herdr-app/mods/agent-quota-bar/collector.py
   ```
