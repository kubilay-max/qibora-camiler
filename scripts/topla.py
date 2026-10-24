#!/usr/bin/env python3
"""
Dünyadaki camileri OpenStreetMap'ten (Overpass) toplar ve 1°×1° kare dosyalarına böler.

- Dünya 10°×10° kutularla taranır; çok yoğun bir kutu zaman aşımına uğrarsa 4 parçaya bölünür
  (en küçük 1,25°). Sunuculara nazik davranılır: istekler arası bekleme, hata olursa artan bekleme
  ve sunucu değiştirme.
- Çıktı: t/<enlem>_<boylam>.json  (enlem/boylam = karenin güneybatı köşesi, tam sayı)
  İçerik: [[enlem, boylam, "ad", {"ar": "...", "en": "..."}], ...]
- Bir kutu en sonunda yine alınamazsa o bölgedeki ESKİ kare dosyaları korunur (veri kaybolmaz).
"""
import json, os, sys, time, math, glob, urllib.request, urllib.parse

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIKTI = os.path.join(KOK, 't')
SUNUCULAR = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.private.coffee/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
]
# Uygulamanın dilleri: bu dillerdeki "name:xx" adları da saklanır
DILLER = ['en','tr','ar','id','ms','bn','ur','hi','fa','ps','ckb','ku','az','uz','kk','ky','tk','tg','ru','sq','bs',
          'fr','de','es','pt','it','nl','ha','yo','sw','so','am','ml','ta','th','ja','ko']
BEKLE = 4          # istekler arası (sn)
EN_KUCUK = 1.25    # bölünebilecek en küçük kutu (derece)
UA = 'QiboraMosqueTiles/1.0 (+https://kubilay-max.github.io/qibora/; contact miswakapp@gmail.com)'

def sorgu(s, w, n, e):
    return (f'[out:json][timeout:170];'
            f'nwr["amenity"="place_of_worship"]["religion"="muslim"]({s},{w},{n},{e});'
            f'out center tags qt;')

sunucu_sira = 0
def iste(s, w, n, e):
    """Kutuyu ister. Başarılıysa öğe listesi; kutu çok büyükse 'BOL'; başarısızsa None."""
    global sunucu_sira
    for deneme in range(6):
        sunucu = SUNUCULAR[sunucu_sira % len(SUNUCULAR)]
        try:
            veri = urllib.parse.urlencode({'data': sorgu(s, w, n, e)}).encode()
            istek = urllib.request.Request(sunucu, data=veri, headers={'User-Agent': UA})
            with urllib.request.urlopen(istek, timeout=200) as y:
                govde = y.read()
            j = json.loads(govde)
            uyari = j.get('remark', '')
            if 'runtime error' in uyari or 'timed out' in uyari or 'out of memory' in uyari:
                return 'BOL'
            return j.get('elements', [])
        except urllib.error.HTTPError as h:
            print(f'   {sunucu.split("/")[2]} HTTP {h.code}', flush=True)
            if h.code in (400,):
                return None
            # 429/504: yoğun — bekle, sunucu değiştir
        except Exception as x:
            print(f'   {sunucu.split("/")[2]} hata: {x}', flush=True)
        sunucu_sira += 1
        time.sleep(min(120, 15 * (2 ** deneme)))
    return None

def kutu_tara(s, w, n, e, kareler, eksik):
    elemanlar = iste(s, w, n, e)
    time.sleep(BEKLE)
    boy = n - s
    if elemanlar == 'BOL' or (elemanlar is None and boy > EN_KUCUK):
        if boy <= EN_KUCUK:
            eksik.append((s, w, n, e)); return
        y = boy / 2
        print(f'  bölünüyor {s},{w} ({boy}°)', flush=True)
        for (a, b) in ((s, w), (s, w + y), (s + y, w), (s + y, w + y)):
            kutu_tara(a, b, a + y, b + y, kareler, eksik)
        return
    if elemanlar is None:
        eksik.append((s, w, n, e)); return
    for el in elemanlar:
        lat = el.get('lat', el.get('center', {}).get('lat'))
        lon = el.get('lon', el.get('center', {}).get('lon'))
        if lat is None or lon is None:
            continue
        t = el.get('tags', {})
        adlar = {d: t[f'name:{d}'] for d in DILLER if t.get(f'name:{d}')}
        kayit = [round(lat, 5), round(lon, 5), t.get('name', '')]
        if adlar:
            kayit.append(adlar)
        anahtar = f'{math.floor(lat)}_{math.floor(lon)}'
        kareler.setdefault(anahtar, {})[f'{el["type"][0]}{el["id"]}'] = kayit

def main():
    os.makedirs(CIKTI, exist_ok=True)
    kareler, eksik = {}, []
    adim = 10
    kutular = [(s, w) for s in range(-60, 80, adim) for w in range(-180, 180, adim)]
    for i, (s, w) in enumerate(kutular):
        print(f'[{i+1}/{len(kutular)}] {s},{w}', flush=True)
        kutu_tara(s, w, s + adim, w + adim, kareler, eksik)

    # Alınamayan bölgelerdeki eski kareleri koru
    korunan = set()
    for (s, w, n, e) in eksik:
        for la in range(math.floor(s), math.ceil(n)):
            for lo in range(math.floor(w), math.ceil(e)):
                korunan.add(f'{la}_{lo}')
    eski = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(CIKTI, '*.json'))}
    for k in eski - set(kareler) - korunan:
        os.remove(os.path.join(CIKTI, k + '.json'))
    for k, d in kareler.items():
        if k in korunan and os.path.exists(os.path.join(CIKTI, k + '.json')):
            continue
        with open(os.path.join(CIKTI, k + '.json'), 'w', encoding='utf-8') as f:
            json.dump(sorted(d.values(), key=lambda r: (r[0], r[1])), f, ensure_ascii=False, separators=(',', ':'))
    toplam = sum(len(d) for d in kareler.values())
    with open(os.path.join(KOK, 'bilgi.json'), 'w') as f:
        json.dump({'guncelleme': time.strftime('%Y-%m-%d'), 'cami': toplam, 'kare': len(kareler),
                   'alinamayan_kutu': len(eksik)}, f, indent=1)
    print(f'BİTTİ: {toplam} cami, {len(kareler)} kare, alınamayan kutu: {len(eksik)}', flush=True)
    if toplam < 1000:
        sys.exit('Çok az cami geldi; bir şey ters gitti, dosyalar yazıldı ama kontrol edin.')

if __name__ == '__main__':
    main()
