plugins {
    id("com.android.application")
}

android {
    namespace = "dev.tarjim.tv"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.tarjim.tv"
        minSdk = 26
        // Sideload only; matches the TV's reported API level (Android 11).
        targetSdk = 30
        versionCode = 3
        versionName = "0.4.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        disable += "ExpiredTargetSdkVersion"
    }
}
