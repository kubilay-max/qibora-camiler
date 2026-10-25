# Qibora – cami ve helal yer verisi

Qibora ve Miswak uygulamaları için dünya genelindeki camilerin ve helal yemek yerlerinin
1°×1° karelere bölünmüş verisi. GitHub Actions ile her ay OpenStreetMap'ten (Geofabrik dosyaları) otomatik güncellenir.

- `t/<enlem>_<boylam>.json` — camiler: `[enlem, boylam, "ad", {"dil": "ad"}]`
- `h/<enlem>_<boylam>.json` — helal yerler: `[enlem, boylam, "ad", "tür", tamamen_helal, "mutfak", {"dil": "ad"}]`
  - tür: `r` restoran, `f` fast food, `c` kafe, `k` kasap, `m` market, `p` fırın/pastane, `d` diğer
  - tamamen_helal: `1` = `diet:halal=only`, `0` = helal seçenek var (`diet:halal=yes`)
- `bilgi.json` — son güncelleme tarihi ve sayılar

Kare bulunamazsa (404) o karede kayıt yok demektir.

## Lisans
Veri © OpenStreetMap katkıcıları, [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) lisansıyla.
Bu veritabanı da ODbL ile paylaşılır. https://www.openstreetmap.org/copyright
