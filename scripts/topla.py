#!/usr/bin/env python3
"""
Dünyadaki camileri OpenStreetMap'ten toplar ve 1°×1° kare dosyalarına böler.

1) Önce QLever (OSM'nin tamamını tutan SPARQL veritabanı): bütün camiler tek sorguda gelir.
2) Olmazsa Overpass'a 10°×10° bölgeler halinde sorar; KALDIĞI YERDEN DEVAM EDER:
   her bölge bitince kareleri yazar, 25 bölgede bir depoya kaydeder (git push). Süre biterse
   bir sonraki çalışma (her gün) kaldığı yerden sürer. Bir ay içinde bütün bölgeler bitince durur.

Çıktı: t/<enlem>_<boylam>.json  = [[enlem, boylam, "ad", {"dil": "ad"}], ...]
       bilgi.json              = son güncelleme bilgisi
"""
import csv, io, json, math, os, re, subprocess, sys, time, urllib.parse, urllib.request

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIKTI = os.path.join(KOK, 't')
DURUM = os.path.join(KOK, 'durum.json')
UA = 'QiboraMosqueTiles/2.0 (+https://kubilay-max.github.io/qibora/; miswakapp@gmail.com)'
DILLER = ['en','tr','ar','id','ms','bn','ur','hi','fa','ps','ckb','ku','az','uz','kk','ky','tk','tg','ru','sq','bs',
          'fr','de','es','pt','it','nl','ha','yo','sw','so','am','ml','ta','th','ja','ko']
SURE_SINIRI = 300 * 60   # bir çalışmada en fazla 5 saat çalış, sonra kaydet ve çık
BASLANGIC = time.time()
AY = time.strftime('%Y-%m')

def log(*a):
    print(*a, flush=True)

def kare_anahtari(lat, lon):
    return f'{math.floor(lat)}_{math.floor(lon)}'

def kayit_yap(lat, lon, ad, adlar):
    k = [round(lat, 5), round(lon, 5), ad or '']
    if adlar:
        k.append(adlar)
    return k

def kareleri_yaz(kareler, silinecek_kutular=None):
    """kareler: {anahtar: [kayit,...]}. silinecek_kutular verilirse o kutulardaki eski boş kareler silinir."""
    os.makedirs(CIKTI, exist_ok=True)
    for k, liste in kareler.items():
        liste.sort(key=lambda r: (r[0], r[1]))
        with open(os.path.join(CIKTI, k + '.json'), 'w', encoding='utf-8') as f:
            json.dump(liste, f, ensure_ascii=False, separators=(',', ':'))
    if silinecek_kutular:
        for (s, w, n, e) in silinecek_kutular:
            for la in range(s, n):
                for lo in range(w, e):
                    k = f'{la}_{lo}'
                    p = os.path.join(CIKTI, k + '.json')
                    if k not in kareler and os.path.exists(p):
                        os.remove(p)

def bilgi_yaz(kaynak, tamam):
    dosyalar = [f for f in os.listdir(CIKTI) if f.endswith('.json')] if os.path.isdir(CIKTI) else []
    toplam = 0
    for f in dosyalar:
        with open(os.path.join(CIKTI, f), encoding='utf-8') as d:
            toplam += len(json.load(d))
    with open(os.path.join(KOK, 'bilgi.json'), 'w') as f:
        json.dump({'guncelleme': time.strftime('%Y-%m-%d'), 'kaynak': kaynak, 'tamam': tamam,
                   'cami': toplam, 'kare': len(dosyalar)}, f, indent=1)
    log(f'bilgi: {toplam} cami, {len(dosyalar)} kare, kaynak={kaynak}, tamam={tamam}')

def git_kaydet(mesaj):
    """Ara kayıt: veriyi depoya gönder (Actions içinde çalışırken)."""
    if not os.environ.get('GITHUB_ACTIONS'):
        return
    try:
        subprocess.run(['git', 'add', '-A', 't', 'bilgi.json', 'durum.json'], cwd=KOK, check=True)
        r = subprocess.run(['git', 'commit', '-m', mesaj], cwd=KOK)
        if r.returncode == 0:
            subprocess.run(['git', 'pull', '--rebase', '-X', 'ours'], cwd=KOK)
            subprocess.run(['git', 'push'], cwd=KOK, check=True)
            log('  ↳ depoya kaydedildi')
    except Exception as x:
        log('  ↳ kayıt hatası:', x)

# ------------------------------------------------------------------ 1) QLever
QLEVER = ['https://qlever.dev/api/osm-planet', 'https://qlever.cs.uni-freiburg.de/api/osm-planet']
ONEK = '''PREFIX osmkey: <https://www.openstreetmap.org/wiki/Key:>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
PREFIX geof: <http://www.opengis.net/def/function/geosparql/>
'''
Q_KONUM = ONEK + '''SELECT ?osm ?merkez ?ad WHERE {
  ?osm osmkey:amenity "place_of_worship" ; osmkey:religion "muslim" ; geo:hasGeometry/geo:asWKT ?g .
  BIND(geof:centroid(?g) AS ?merkez)
  OPTIONAL { ?osm osmkey:name ?ad }
}'''
Q_ADLAR = ONEK + '''SELECT ?osm ?k ?v WHERE {
  ?osm osmkey:amenity "place_of_worship" ; osmkey:religion "muslim" ; ?k ?v .
  FILTER(STRSTARTS(STR(?k), "https://www.openstreetmap.org/wiki/Key:name:"))
}'''

def qlever_sor(sorgu):
    for uc in QLEVER:
        for deneme in range(3):
            try:
                veri = urllib.parse.urlencode({'query': sorgu}).encode()
                istek = urllib.request.Request(uc, data=veri, headers={
                    'User-Agent': UA, 'Accept': 'text/tab-separated-values',
                    'Content-Type': 'application/x-www-form-urlencoded'})
                with urllib.request.urlopen(istek, timeout=900) as y:
                    metin = y.read().decode('utf-8')
                satirlar = metin.split('\n')
                log(f'  QLever {uc.split("/")[2]}: {len(satirlar) - 1} satır')
                return satirlar
            except Exception as x:
                log(f'  QLever {uc.split("/")[2]} hata: {x}')
                time.sleep(20 * (deneme + 1))
    return None

def tsv_deger(s):
    """TSV hücresi: <iri>, "metin"@dil, "metin"^^<tip>, ya da düz değer"""
    s = s.strip()
    if s.startswith('<') and s.endswith('>'):
        return s[1:-1]
    m = re.match(r'^"(.*)"(?:@[\w-]+|\^\^<[^>]*>)?$', s, re.S)
    if m:
        return m.group(1).replace('\\"', '"').replace('\\\\', '\\').replace('\\n', ' ').replace('\\t', ' ')
    return s

def qlever_topla():
    log('QLever ile deneniyor…')
    satirlar = qlever_sor(Q_KONUM)
    if not satirlar or len(satirlar) < 50000:
        log('QLever yeterli veri vermedi.')
        return None
    yer = {}
    for satir in satirlar[1:]:
        if not satir.strip():
            continue
        p = satir.split('\t')
        if len(p) < 2:
            continue
        iri, wkt = tsv_deger(p[0]), tsv_deger(p[1])
        ad = tsv_deger(p[2]) if len(p) > 2 else ''
        m = re.search(r'POINT\s*\(\s*([-\d.eE]+)\s+([-\d.eE]+)\s*\)', wkt)
        if not m:
            continue
        lon, lat = float(m.group(1)), float(m.group(2))
        kimlik = iri.rsplit('/', 2)[-2][0] + iri.rsplit('/', 1)[-1]  # node/123 -> n123
        if kimlik not in yer:
            yer[kimlik] = [lat, lon, ad, {}]
    log(f'  konumlu cami: {len(yer)}')
    adlar = qlever_sor(Q_ADLAR) or []
    for satir in adlar[1:]:
        p = satir.split('\t')
        if len(p) < 3:
            continue
        iri, k, v = tsv_deger(p[0]), tsv_deger(p[1]), tsv_deger(p[2])
        dil = k.rsplit('name:', 1)[-1]
        kimlik = iri.rsplit('/', 2)[-2][0] + iri.rsplit('/', 1)[-1]
        if dil in DILLER and kimlik in yer:
            yer[kimlik][3][dil] = v
    kareler = {}
    for lat, lon, ad, ad_dil in yer.values():
        kareler.setdefault(kare_anahtari(lat, lon), []).append(kayit_yap(lat, lon, ad, ad_dil))
    return kareler

# ------------------------------------------------------------------ 2) Overpass (devam edebilen)
OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://overpass.private.coffee/api/interpreter',
            'https://maps.mail.ru/osm/tools/overpass/api/interpreter']
ADIM = 10
EN_KUCUK = 2.5
sira = 0

def overpass_iste(s, w, n, e):
    global sira
    q = (f'[out:json][timeout:120];nwr["amenity"="place_of_worship"]["religion"="muslim"]'
         f'({s},{w},{n},{e});out center tags qt;')
    for deneme in range(4):
        uc = OVERPASS[sira % len(OVERPASS)]
        try:
            veri = urllib.parse.urlencode({'data': q}).encode()
            with urllib.request.urlopen(urllib.request.Request(uc, data=veri, headers={'User-Agent': UA}), timeout=150) as y:
                j = json.loads(y.read())
            if any(t in j.get('remark', '') for t in ('runtime error', 'timed out', 'out of memory')):
                return 'BOL'
            return j.get('elements', [])
        except urllib.error.HTTPError as h:
            log(f'   {uc.split("/")[2]} HTTP {h.code}')
        except Exception as x:
            log(f'   {uc.split("/")[2]} hata: {x}')
        sira += 1
        time.sleep([10, 30, 60, 90][deneme])
    return None

def overpass_kutu(s, w, n, e, kareler):
    """True: kutu tamam; False: alınamadı"""
    el = overpass_iste(s, w, n, e)
    time.sleep(3)
    if el == 'BOL' or (el is None and n - s > EN_KUCUK):
        y = (n - s) / 2
        if y < EN_KUCUK / 2:
            return False
        ok = True
        for (a, b) in ((s, w), (s, w + y), (s + y, w), (s + y, w + y)):
            ok = overpass_kutu(a, b, a + y, b + y, kareler) and ok
        return ok
    if el is None:
        return False
    for x in el:
        lat = x.get('lat', x.get('center', {}).get('lat'))
        lon = x.get('lon', x.get('center', {}).get('lon'))
        if lat is None or lon is None:
            continue
        t = x.get('tags', {})
        ad_dil = {d: t[f'name:{d}'] for d in DILLER if t.get(f'name:{d}')}
        kareler.setdefault(kare_anahtari(lat, lon), {})[f'{x["type"][0]}{x["id"]}'] = kayit_yap(lat, lon, t.get('name'), ad_dil)
    return True

def overpass_topla():
    durum = {'ay': AY, 'tamam': []}
    if os.path.exists(DURUM):
        with open(DURUM) as f:
            d = json.load(f)
        if d.get('ay') == AY:
            durum = d
    kutular = [(s, w) for s in range(-60, 80, ADIM) for w in range(-180, 180, ADIM)]
    kalan = [k for k in kutular if f'{k[0]}_{k[1]}' not in durum['tamam']]
    log(f'Overpass: {len(kutular) - len(kalan)}/{len(kutular)} bölge bu ay tamamlanmış, {len(kalan)} kaldı')
    son_kayit = 0
    for i, (s, w) in enumerate(kalan):
        if time.time() - BASLANGIC > SURE_SINIRI:
            log('Süre doldu; kalan bölgeler bir sonraki çalışmada.')
            break
        log(f'[{i + 1}/{len(kalan)}] bölge {s},{w}')
        kareler = {}
        if overpass_kutu(s, w, s + ADIM, w + ADIM, kareler):
            kareleri_yaz({k: list(v.values()) for k, v in kareler.items()}, [(s, w, s + ADIM, w + ADIM)])
            durum['tamam'].append(f'{s}_{w}')
            with open(DURUM, 'w') as f:
                json.dump(durum, f)
        else:
            log('  bölge alınamadı, sonra tekrar denenecek (eski veri korunuyor)')
        if len(durum['tamam']) - son_kayit >= 25:
            son_kayit = len(durum['tamam'])
            bilgi_yaz('overpass', False)
            git_kaydet(f'Cami verisi: {len(durum["tamam"])}/{len(kutular)} bölge')
    tamam = len(durum['tamam']) == len(kutular)
    bilgi_yaz('overpass', tamam)
    return tamam

# ------------------------------------------------------------------
def main():
    # Bu ay zaten tamamlandıysa hiçbir şey yapma (günlük çalışma bunu kontrol eder)
    if os.path.exists(os.path.join(KOK, 'bilgi.json')) and not os.environ.get('ZORLA'):
        with open(os.path.join(KOK, 'bilgi.json')) as f:
            b = json.load(f)
        if b.get('tamam') and b.get('guncelleme', '')[:7] == AY:
            log(f'Bu ay ({AY}) veri zaten tamam; çıkılıyor.')
            return
    kareler = qlever_topla()
    if kareler:
        # Tam veri geldi: bütün kareleri yeniden yaz, artık camisi olmayan kareleri sil
        os.makedirs(CIKTI, exist_ok=True)
        for f in os.listdir(CIKTI):
            if f.endswith('.json') and f[:-5] not in kareler:
                os.remove(os.path.join(CIKTI, f))
        kareleri_yaz(kareler)
        with open(DURUM, 'w') as f:
            json.dump({'ay': AY, 'tamam': 'qlever'}, f)
        bilgi_yaz('qlever', True)
        return
    overpass_topla()

if __name__ == '__main__':
    main()
