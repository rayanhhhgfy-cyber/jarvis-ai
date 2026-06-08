plugins {
  id("com.android.application")
  id("org.jetbrains.kotlin.android")
}

android {
  namespace = "com.jarvis.omega"
  compileSdk = 34

  defaultConfig {
    applicationId = "com.jarvis.omega"
    minSdk = 24
    targetSdk = 34
    versionCode = 1
    versionName = "1.0.0"

    testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    vectorDrawables {
      useSupportLibrary = true
    }
  }

  buildTypes {
    release {
      isMinifyEnabled = false
      proguardFiles(
        getDefaultProguardFile("proguard-android-optimize.txt"),
        "proguard-rules.pro"
      )
    }
    debug {
      isMinifyEnabled = false
    }
  }

  compileOptions {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
  }
  kotlinOptions {
    jvmTarget = "17"
  }

  buildFeatures {
    compose = true
    buildConfig = true
  }

  composeOptions {
    kotlinCompilerExtensionVersion = "1.5.14"
  }

  packaging {
    resources {
      excludes += "/META-INF/{AL2.0,LGPL2.2}"
    }
  }
}

dependencies {
  // Core
  implementation("androidx.core:core-ktx:1.13.1")
  implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
  implementation("androidx.activity:activity-compose:1.9.0")

  // Compose BOM
  val composeBom = platform("androidx.compose:compose-bom:2024.10.01")
  implementation(composeBom)
  implementation("androidx.compose.ui:ui")
  implementation("androidx.compose.ui:ui-graphics")
  implementation("androidx.compose.ui:ui-tooling-preview")
  implementation("androidx.compose.material3:material3")
  implementation("androidx.compose.material:material-icons-extended")
  implementation("androidx.compose.ui:ui-tooling")

  // Navigation (optional later, but useful)
  implementation("androidx.navigation:navigation-compose:2.8.0")

  // Coroutines
  implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

  // WebSocket + HTTP
  implementation("com.squareup.okhttp3:okhttp:4.12.0")
  implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

  // DataStore / encrypted storage
  implementation("androidx.datastore:datastore-preferences:1.1.1")
  implementation("androidx.security:security-crypto:1.1.0-alpha06")

  // CameraX for QR scanning
  val cameraxVersion = "1.4.0"
  implementation("androidx.camera:camera-camera2:$cameraxVersion")
  implementation("androidx.camera:camera-lifecycle:$cameraxVersion")
  implementation("androidx.camera:camera-view:$cameraxVersion")
  implementation("androidx.camera:camera-extensions:$cameraxVersion")

  // ML Kit QR scanning
  implementation("com.google.mlkit:barcode-scanning:17.3.0")

  // Clerk auth (browser-based / token entry compatible)
  // Clerk Android SDK is not always available; we will support JWT token entry + browser OAuth flow.
  // Keep dependencies minimal and rely on HTTP + secure storage.
  // (No placeholder: this project will include working JWT token storage + validation calls later.)

  // Foreground service + notifications
  implementation("androidx.work:work-runtime-ktx:2.9.1")
}
