# Yedi Yirmi Dort

Mavi yaka çalışan deneyimi için Android uygulaması ve Flask/MongoDB backend'i.

## Projeler

- `m7_24`: Kotlin, Jetpack Compose Android uygulaması
- `b7_24`: Flask API, yönetim paneli, MongoDB ve arka plan işçileri

Kurulum, yapılandırma ve operasyon ayrıntıları her projenin kendi README
dosyasındadır.

## Doğrulama

Backend testleri yerel MongoDB'nin `localhost:27017` adresinde çalışmasını
bekler:

```bash
cd b7_24
./.venv/bin/python -m pytest --quiet
```

Android doğrulamaları:

```bash
cd m7_24
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
./gradlew :app:connectedDebugAndroidTest
```

`.github/workflows/ci.yml`, her push ve pull request için:

- MongoDB 8 üzerinde backend testlerini çalıştırır.
- Python kaynaklarını derler, Bandit ve `pip-audit` kontrollerini uygular.
- Android unit test, lint ve debug build adımlarını çalıştırır.
- API 35 başsız emülatörde Android instrumented testlerini çalıştırır.
- Production compose şemasını ve backend container build'ini doğrular.

Dependabot; GitHub Actions, Python ve Gradle bağımlılıklarını haftalık olarak
izler.

## Production Yayını

Production yayını öncesinde kaynak kontrolüne eklenmeyecek gerçek ortam
değerleri sağlanmalıdır:

- TLS etkin ve kimlik doğrulamalı MongoDB URI
- Twilio SMS bilgileri
- Firebase proje kimliği, servis hesabı ve Android `google-services.json`
- Android release keystore ve imzalama bilgileri
- Gerçek gizlilik politikası ve uygulama mağazası URL'leri

Backend preflight ve Android imzalı release komutları için
`b7_24/README.md` ve `m7_24/README.md` kullanılmalıdır.
