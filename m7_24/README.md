# Yedi Yirmi Dört Android

Kotlin, Jetpack Compose ve CameraX tabanlı çalışan uygulaması.

Uygulama açılışında herkese açık mobil config endpointi kontrol edilir.
Bakım modunda kullanıcı akışı açılmaz; kurulu `versionCode` sunucunun minimum
değerinden düşükse yalnızca zorunlu güncelleme aksiyonu gösterilir. Bağlantı
hatası kullanıcı kontrollü olarak yeniden denenebilir.
Çalışan panelinde değerlendirme cevapları sunucuda puanlanır; eğitimler her
modül ayrı ayrı onaylandıktan sonra tamamlanabilir. İşveren çalışana özel
içerik ataması kaydettiğinde panel yalnızca atanmış ve
yayındaki değerlendirme/eğitimleri gösterir; özel atama yoksa yayındaki tüm
işveren içeriği görünür.
Başarısız değerlendirmeler yeniden çözülebilir; son puan ve deneme sayısı
panelde güncellenir. Eğitim modülü seçimleri tamamlanmadan da kaydedilir ve
sonraki oturumda kaldığı yerden devam eder.
Çalışanın iş başvurusu geçmişi, ilgili ilan veya öneri yayından kalksa da
panelde kalır. Yeni, incelenen veya kısa listeye alınan başvurular açık bir
onaydan sonra çalışan tarafından geri çekilebilir. Aktif servis talepleri de
çalışan tarafından iptal edilip daha sonra yeniden oluşturulabilir.
İşveren incelenen veya kısa listedeki başvuruya görüşme tarihi, görüşme türü,
konum ve hazırlık notu eklediğinde plan başvuru kartında yerel saatle
gösterilir. Planlama ve yeniden planlama değişiklikleri arka plan kontrolünde
ve yapılandırılmış push bildirimlerinde çalışana bildirilir. Çalışan görüşmeye
katılacağını onaylayabilir veya zorunlu bir gerekçeyle katılamayacağını
işverene iletebilir. İşveren planı değiştirdiğinde önceki çalışan yanıtı
sıfırlanır ve yeni plan yeniden onay bekler.
İşveren başlangıç ve son yanıt tarihi belirleyerek iş teklifi gönderdiğinde
teklif başvuru kartında gösterilir. Çalışan açık bir onayla teklifi kabul edip
işe alım durumuna geçebilir veya zorunlu gerekçeyle reddedebilir. Süresi dolan
teklifler backend tarafından kabul edilmez; ret halinde ayrılan ilan
kontenjanı yeniden kullanılabilir hale gelir.
Bekleyen çalışan soruları,
ekran açıkken 15 saniyede bir yenilenir ve üst çubuktaki yenile ikonu ile
istenildiğinde hemen güncellenebilir. Soru, değerlendirme, eğitim, servis ve iş
başvurusu istekleri UUID tabanlı idempotency anahtarı kullanır; devam eden
çalışan işlemleri tamamlanana kadar ilgili kontroller kilitlenir.
Aktif iş başvuruları ve bekleyen servis talepleri işveren kararı gelene kadar
60 saniyede bir yenilenir.
Oturum açıkken WorkManager, ağ bağlantısı bulunduğunda paneli en az 15
dakikalık sistem aralığıyla arka planda kontrol eder. Başvuru veya servis
durumu değiştiğinde ve işveren bekleyen bir soruyu yanıtladığında yerel bildirim
oluşturulur. Android 13 ve üzerindeki kullanıcı bildirim iznini çalışan
panelinden açar. Firebase yapılandırılmış üretim derlemesi aynı olayları FCM
veri mesajı olarak anlık alır. Uygulama Firebase Installation ID'yi (FID)
backend'e gönderir; backend yanıtında veya kişisel veri exportunda FID yer
almaz. Olay kimliği cihazda tekilleştirilir ve yerel panel özeti güncellenir;
böylece 15 dakikalık WorkManager güvenlik ağı aynı olayı ikinci kez bildirmez.
Çıkış ve hesap silme FCM kaydını yerel olarak kapatır.
Video yüklemesi dosyanın SHA-256 özetiyle doğrulanır. Başarısız bir aktarım
aynı idempotency anahtarıyla yeniden denenebilir; böylece yanıt kaybolsa bile
ikinci bir video işleme kaydı oluşturulmaz.
Kayıt ve telefon doğrulama akışında ad soyad istenmez. Video işleme ad soyadı
konuşmadan çıkardıktan sonra çalışan paneli bu değeri zorunlu olarak onaylatır
veya düzelttirir. Çalışanın onayladığı ad mevcut başvurulara yansıtılır ve
sonraki video işlemleri tarafından değiştirilmez.
Kamera kaydı 90 saniye ve 150 MB ile sınırlıdır. Sunucunun kabul ettiği yerel
ham kayıt hemen, yarım kalmış cache kayıtları ise 24 saat sonra uygulama
açılışında silinir.
Kamera ve mikrofon izninden önce backend'in yayınladığı güncel video işleme
onayı kontrol edilir. Daha önce kabul edilmemiş sürüm için kullanıcıya işleme
amacı, ham video silme davranışı ve gizlilik metni gösterilir; checkbox açıkça
işaretlenip onay backend'e kaydedilmeden kamera ekranı açılmaz. Onay geri
çekilirse sonraki video yüklemeleri backend tarafından engellenir. Çalışan
onayı hesap bölümünden ikinci bir açık doğrulamayla geri çekebilir; mevcut
profil ve transkript ancak hesap silme akışıyla kaldırılır.
Kamera ekranından kayıt sırasında çıkılırsa aktif kayıt durdurulur, sonuç
yükleme ekranına gönderilmez ve oluşan geçici dosya silinir.
Telefon doğrulama kodu sunucunun bildirdiği bekleme süresi dolduğunda aynı
ekrandan yeniden istenebilir.
Çalışan panelindeki hesap alanı, ikinci bir açık onaydan sonra backend kişisel
veri silme akışını çalıştırır ve başarılı yanıtta şifreli yerel oturumu
temizler. İş başvurularının kimliksizleştirilmiş operasyon kaydı olarak
tutulduğu onay penceresinde açıkça belirtilir.
Çalışan aynı hesap alanından kişisel verilerini sürümlü JSON paketi olarak
dışa aktarabilir. Dosya 25 MB ile sınırlı özel cache alanına yazılır, dışa
kapalı `FileProvider` URI'siyle sistem paylaşım ekranına verilir ve 24 saat
sonra otomatik silinir.
Çıkış, hesap silme veya 401 ile oturum düşmesi halinde yerel video ve veri
export cache'i beklemeden temizlenir. Uygulama oturumsuz açıldığında da önceki
çalışandan kalabilecek özel cache dosyaları kaldırılır.

## Local emulator

Backend `5050` portunda çalışırken:

```bash
./gradlew :app:assembleDebug \
  -PAPI_BASE_URL=http://10.0.2.2:5050/
```

```bash
$HOME/Library/Android/sdk/platform-tools/adb \
  install -r app/build/outputs/apk/debug/app-debug.apk
```

Debug build emülatör için cleartext HTTP bağlantısına izin verir. Fiziksel
cihazda backend adresi olarak geliştirme makinesinin LAN IP adresini kullanın.
`app/google-services.json` yoksa FCM servisi derlemede devre dışı kalır ve
emülatörde WorkManager yedeği çalışmaya devam eder.

## Firebase

Firebase Console'da production için seçilen Android paket adıyla uygulamayı
oluşturun ve indirilen yapılandırmayı `app/google-services.json` olarak
yerleştirin. Bu paket adı production komutundaki `APPLICATION_ID` ile aynı
olmalıdır. Dosya git tarafından yok sayılır. Firebase Cloud Messaging API
etkin olmalı ve backend push worker aynı `FCM_PROJECT_ID` ile çalışmalıdır.
Uygulama açılışında FCM kaydı yenilenir; `onRegistered` ile gelen güncel FID
worker yetkili cihaz endpointine yüklenir.

## Validation

```bash
./gradlew :app:testDebugUnitTest :app:lintDebug
./gradlew :app:connectedDebugAndroidTest
```

## Release

Release build cleartext trafiği reddeder ve açıkça HTTPS API adresi ister:

```bash
./gradlew :app:assembleRelease \
  -PAPI_BASE_URL=https://api.example.com/
```

Release build R8 küçültme ve resource shrinking kullanır. İmzalı Play Store
paketi için güvenli CI secret'ları veya `~/.gradle/gradle.properties` üzerinden
`RELEASE_STORE_FILE`, `RELEASE_STORE_PASSWORD`, `RELEASE_KEY_ALIAS` ve
`RELEASE_KEY_PASSWORD` değerlerini sağlayın. İmza anahtarlarını ve parolaları
repoya eklemeyin.

Production paketi `app/google-services.json`, sürüm bilgisi, HTTPS API ve tam
imza yapılandırması yoksa başlamadan hata verir:

```bash
./gradlew productionRelease \
  -PAPPLICATION_ID=com.yediyirmidort.worker \
  -PAPI_BASE_URL=https://api.example.com/ \
  -PVERSION_CODE=1 \
  -PVERSION_NAME=1.0.0
```

Çıktı `app/build/outputs/bundle/release/app-release.aab` altında oluşur.
`productionRelease`, placeholder `com.example.*` paket kimliğini reddeder.
