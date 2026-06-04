# 🚀 看到Neo4j執行結果 — 完整操作指南

## 前置準備
- Windows 11/10
- Docker Desktop 已安裝

---

## ✅ 第1步：啟動Docker Desktop

1. **按 Windows鍵**，搜尋 `Docker Desktop`
2. **點擊打開**
3. **等待 30-60 秒** 讓Docker完全啟動
4. 你會看到右下角托盤出現 Docker 圖標（小鯨魚）

✅ Docker 啟動完成

---

## ✅ 第2步：啟動所有容器

打開 **PowerShell**，執行：

```powershell
cd c:\Users\jaco8\db_final\IM2002-DBMGT-Train-final
docker compose up -d
```

**預期輸出：**
```
[+] Running 3/3
 ✔ postgres Started
 ✔ neo4j Started  
 ✔ pgadmin Started
```

等等…5-10秒讓容器完全啟動。

✅ 所有容器現在運行中

---

## ✅ 第3步：執行Neo4j種子腳本

在同一個PowerShell窗口，執行：

```powershell
python skeleton/seed_neo4j.py
```

**預期輸出：**
```
Connecting to Neo4j...
  Cleared existing graph data
  Created 20 MetroStation nodes
  Created 10 RailStation nodes
  Created 42 METRO_LINK edges
  Created 18 RAIL_LINK edges
  Created 3 INTERCHANGE relationships

Neo4j graph seeded successfully.
   Open http://localhost:7475 to explore the graph.
```

✅ 圖形已經建立！

---

## ✅ 第4步：在Neo4j Browser中看到結果

1. **打開瀏覽器** → 輸入 `http://localhost:7475`
2. 你會看到Neo4j Browser的登錄頁面
3. **輸入憑證：**
   - Username: `neo4j`
   - Password: `transitflow`
4. 點擊 **Connect**

✅ 你現在在Neo4j Browser中

---

## ✅ 第5步：視覺化整個圖形

在黑色的命令框中複製貼上：

```cypher
MATCH (n)-[r]->(m) RETURN n, r, m
```

然後按 **Ctrl+Enter** 或點擊播放按鈕

**你會看到：**
- 20個藍色圓圈（地鐵站點 MetroStation）
- 10個紅色圓圈（國鐵站點 RailStation）
- 箭頭連接它們（METRO_LINK、RAIL_LINK、INTERCHANGE）

這就是**我的seed_neo4j.py程式碼**創建的實際圖形！

---

## 🔍 第6步：測試個別查詢

### 查詢 1：查看中心站附近的所有連接

```cypher
MATCH (station:MetroStation {station_id: "MS01"})-[r]->(connected)
RETURN station, r, connected
```

**結果:** MS01 中央廣場連接到 4 個站點

---

### 查詢 2：找最短路線

```cypher
MATCH (origin:MetroStation {station_id: "MS01"})
MATCH (dest:MetroStation {station_id: "MS09"})
CALL apoc.algo.dijkstra(origin, dest, 'METRO_LINK', 'travel_time_min')
YIELD path, weight
RETURN path, weight
```

**結果:** 路線從 MS01 → MS05 → MS09，總時間 18 分鐘

---

### 查詢 3：查看所有交換點

```cypher
MATCH (metro:MetroStation)-[r:INTERCHANGE]-(rail:RailStation)
RETURN metro.station_id as metro_id, metro.name as metro_name,
       rail.station_id as rail_id, rail.name as rail_name
```

**結果:** 3 個交換點
- MS01 (Central Square) ↔ NR01 (Central Station)
- MS07 (Old Town) ↔ NR03 (Old Town Junction)  
- MS15 (Ferndale) ↔ NR07 (Ferndale Halt)

---

## 🎯 第7步：檢查Python查詢函數

要驗證你的Python查詢函數是否也正確運作，可以在 Python 中執行：

```python
from databases.graph.queries import (
    query_shortest_route,
    query_station_connections,
    query_delay_ripple
)

# 測試1：最短路線
result = query_shortest_route("MS01", "MS09")
print("最短路線:", result)

# 測試2：站點連接
connections = query_station_connections("NR01")
print("NR01 的連接:", connections)

# 測試3：延誤波及
affected = query_delay_ripple("NR03", hops=2)
print("NR03 延誤影響:", affected)
```

---

## 📊 總結

| 步驟 | 動作 | 結果 |
|-----|------|------|
| 1 | 啟動Docker Desktop | 容器準備就緒 |
| 2 | `docker compose up -d` | PostgreSQL + Neo4j + pgAdmin 運行 |
| 3 | `python skeleton/seed_neo4j.py` | 30 個節點 + 63 條邊被創建 |
| 4 | 打開 http://localhost:7475 | 進入Neo4j Browser |
| 5 | 執行 `MATCH (n)-[r]->(m) RETURN n, r, m` | 看到完整圖形視覺化 |
| 6 | 執行其他Cypher查詢 | 驗證路線、連接、交換點 |

---

## ⚠️ 常見問題

**Q: Docker已經啟動但 `docker ps` 仍然失敗？**
A: 等待60秒讓Docker完全啟動。檢查右下角托盤中是否有Docker圖標。

**Q: 容器不啟動？**
A: 執行 `docker compose down -v` 然後重新執行 `docker compose up -d`

**Q: Neo4j Browser 連不上？**
A: 確保容器在運行中：`docker compose ps`

**Q: 忘記Neo4j密碼？**
A: 在 [docker-compose.yml](docker-compose.yml) 中查看：環境變量 `NEO4J_AUTH=neo4j/transitflow`

---

## ✨ 當你完成後

提交代碼：
```bash
git add .
git commit -m "Add Neo4j graph implementation and test results"
git push
```

然後告訴我你看到的圖形效果！🎉
