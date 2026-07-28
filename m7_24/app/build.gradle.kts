import java.net.URI

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

val googleServicesConfigured = file("google-services.json").isFile
if (googleServicesConfigured) {
    apply(plugin = "com.google.gms.google-services")
}

val configuredApiBaseUrl = (project.findProperty("API_BASE_URL") as String?)
    ?.trim()
    ?.takeIf { it.isNotEmpty() }
val releaseRequested = gradle.startParameter.taskNames.any {
    it.contains("release", ignoreCase = true)
}
val productionReleaseRequested = gradle.startParameter.taskNames.any {
    it.contains("productionRelease", ignoreCase = true)
}
fun releaseCredential(name: String): String? {
    return ((project.findProperty(name) as String?)
        ?: System.getenv(name))
        ?.trim()
        ?.takeIf { it.isNotEmpty() }
}
val releaseStoreFile = releaseCredential("RELEASE_STORE_FILE")
val releaseStorePassword = releaseCredential("RELEASE_STORE_PASSWORD")
val releaseKeyAlias = releaseCredential("RELEASE_KEY_ALIAS")
val releaseKeyPassword = releaseCredential("RELEASE_KEY_PASSWORD")
val releaseSigningValues = listOf(
    releaseStoreFile,
    releaseStorePassword,
    releaseKeyAlias,
    releaseKeyPassword,
)
val releaseSigningConfigured = releaseSigningValues.all { it != null }
if (releaseSigningValues.any { it != null } && !releaseSigningConfigured) {
    throw GradleException(
        "Release signing requires RELEASE_STORE_FILE, " +
            "RELEASE_STORE_PASSWORD, RELEASE_KEY_ALIAS, and " +
            "RELEASE_KEY_PASSWORD."
    )
}
if (productionReleaseRequested && !googleServicesConfigured) {
    throw GradleException(
        "productionRelease requires app/google-services.json."
    )
}
if (productionReleaseRequested && !releaseSigningConfigured) {
    throw GradleException(
        "productionRelease requires a complete release signing configuration."
    )
}
val configuredVersionCode = (project.findProperty("VERSION_CODE") as String?)
    ?.toIntOrNull()
val configuredVersionName = (project.findProperty("VERSION_NAME") as String?)
    ?.trim()
    ?.takeIf { it.isNotEmpty() }
val configuredApplicationId =
    (project.findProperty("APPLICATION_ID") as String?)
        ?.trim()
        ?.takeIf { it.isNotEmpty() }
val applicationIdValue =
    configuredApplicationId ?: "com.example.m7_24"
val applicationIdPattern =
    Regex("^[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*){1,}$")
if (!applicationIdPattern.matches(applicationIdValue)) {
    throw GradleException(
        "APPLICATION_ID must be a valid reverse-domain Android package name."
    )
}
if (
    productionReleaseRequested &&
    (
        configuredApplicationId == null ||
            applicationIdValue.startsWith("com.example.")
        )
) {
    throw GradleException(
        "productionRelease requires a non-placeholder APPLICATION_ID."
    )
}
if (productionReleaseRequested && configuredVersionCode == null) {
    throw GradleException("productionRelease requires VERSION_CODE.")
}
if (productionReleaseRequested && configuredVersionName == null) {
    throw GradleException("productionRelease requires VERSION_NAME.")
}
val apiBaseUrl = configuredApiBaseUrl ?: "http://10.0.2.2:5050/"
val parsedApiBaseUrl = runCatching { URI(apiBaseUrl) }.getOrNull()

if (
    parsedApiBaseUrl == null ||
    parsedApiBaseUrl.host.isNullOrBlank() ||
    parsedApiBaseUrl.scheme !in setOf("http", "https") ||
    !apiBaseUrl.endsWith("/")
) {
    throw GradleException(
        "API_BASE_URL must be an absolute HTTP(S) URL ending with '/'."
    )
}
if (releaseRequested && parsedApiBaseUrl?.scheme != "https") {
    throw GradleException(
        "Release builds require an HTTPS API_BASE_URL."
    )
}

android {
    namespace = "com.example.m7_24"
    compileSdk = 36

    defaultConfig {
        applicationId = applicationIdValue
        minSdk = 24
        targetSdk = 36
        versionCode = configuredVersionCode ?: 1
        versionName = configuredVersionName ?: "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "API_BASE_URL", "\"$apiBaseUrl\"")
        buildConfigField(
            "boolean",
            "FCM_ENABLED",
            googleServicesConfigured.toString(),
        )
        manifestPlaceholders["fcmEnabled"] =
            googleServicesConfigured.toString()
    }

    signingConfigs {
        if (releaseSigningConfigured) {
            create("release") {
                storeFile = file(releaseStoreFile!!)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }
    buildTypes {
        debug {
            manifestPlaceholders["usesCleartextTraffic"] = "true"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            manifestPlaceholders["usesCleartextTraffic"] = "false"
            if (releaseSigningConfigured) {
                signingConfig = signingConfigs.getByName("release")
            }
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

tasks.register("productionRelease") {
    group = "build"
    description = "Builds the signed, minified production Android App Bundle."
    dependsOn("bundleRelease")
}

dependencies {

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.camera.camera2)
    implementation(libs.androidx.camera.lifecycle)
    implementation(libs.androidx.camera.view)
    implementation(libs.androidx.camera.video)
    implementation(libs.retrofit)
    implementation(libs.retrofit.converter.gson)
    implementation(libs.okhttp.logging.interceptor)
    implementation(libs.androidx.work.runtime.ktx)
    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.messaging)
    implementation(libs.firebase.installations)

    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    debugImplementation(libs.androidx.compose.ui.tooling)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
}
